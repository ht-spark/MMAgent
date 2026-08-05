import { useEffect, useRef, useState } from 'react'

type Props = { onStart: () => void; onDocs: () => void }

const CAPABILITIES = [
  { icon: 'M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16zM3 9h18M9 21V9', title: '题目解析', desc: '深度理解赛题背景，自动提取关键信息，识别问题类型与约束条件', tag: 'NLP · 知识图谱' },
  { icon: 'M3 3h18v18H3zM3 9h18M9 21V9', title: '模型选择', desc: '基于问题特征智能推荐最优建模方法，覆盖 156+ 经典模型', tag: '决策树 · 匹配算法' },
  { icon: 'M16 18l6-6-6-6M8 6l-6 6 6 6', title: '代码生成', desc: '自动生成 Python / MATLAB 代码，集成 SciPy、PuLP、Gurobi 等工具链', tag: 'Code-LLM · 沙箱执行' },
  { icon: 'M3 3v18h18M7 14l4-4 4 4 6-6', title: '数据可视化', desc: '自动绘制专业级图表，论文级排版，支持 LaTeX 公式嵌入', tag: 'Matplotlib · D3.js' },
  { icon: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2', title: '结果分析', desc: '灵敏度分析、误差评估、模型对比，确保结论科学严谨', tag: '统计分析 · 蒙特卡洛' },
  { icon: 'M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8', title: '论文撰写', desc: '一键生成结构化建模论文，含摘要、模型、求解、结论完整章节', tag: 'LaTeX · 学术规范' },
]

const WORKFLOW = [
  { n: '01', t: '题目理解', d: '自动解析赛题，提取关键信息', dur: '~30s' },
  { n: '02', t: '思路分析', d: '多方案对比，确定建模路径', dur: '~2min' },
  { n: '03', t: '模型建立', d: '选择并构建数学模型', dur: '~5min' },
  { n: '04', t: '算法实现', d: '代码生成与运行验证', dur: '~3min' },
  { n: '05', t: '结果分析', d: '可视化与误差评估', dur: '~2min' },
  { n: '06', t: '论文撰写', d: '一键生成完整论文', dur: '~8min' },
]

export default function Home({ onStart, onDocs }: Props) {
  const [typed, setTyped] = useState('')

  const formulaRef = useRef<HTMLDivElement>(null)
  const miniRef = useRef<HTMLCanvasElement>(null)

  /* Typing animation */
  useEffect(() => {
    const words = ['更智能', '更高效', '更专业', '更轻松', '更有趣']
    let wi = 0, ci = 0, deleting = false, timer = 0
    const tick = () => {
      const word = words[wi]
      if (!deleting) {
        setTyped(word.slice(0, ++ci))
        if (ci === word.length) {
          deleting = true
          timer = window.setTimeout(tick, 1800)
          return
        }
      } else {
        setTyped(word.slice(0, --ci))
        if (ci === 0) {
          deleting = false
          wi = (wi + 1) % words.length
        }
      }
      timer = window.setTimeout(tick, deleting ? 60 : 120)
    }
    tick()
    return () => window.clearTimeout(timer)
  }, [])

  /* KaTeX + Charts */
  useEffect(() => {
    let cancelled = false
    const tryInit = () => {
      const w = window as any
      if (cancelled) return
      if (w.katex && formulaRef.current) {
        try {
          w.katex.render(
            '\\min_{x \\in \\mathbb{R}^n} c^T x \\quad \\text{s.t.} \\quad Ax \\leq b,\\ x \\geq 0',
            formulaRef.current,
            { throwOnError: false, displayMode: true },
          )
        } catch { /* ignore */ }
      }
      if (w.Chart && miniRef.current) {
        drawCharts(w.Chart)
        return
      }
      if (!w.katex || !w.Chart) setTimeout(tryInit, 200)
    }
    const t = setTimeout(tryInit, 100)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [])

  function drawCharts(Chart: any) {
    if (miniRef.current) {
      new Chart(miniRef.current.getContext('2d'), {
        type: 'line',
        data: {
          labels: Array.from({ length: 24 }, (_, i) => i),
          datasets: [{
            data: [12, 8, 5, 3, 2, 4, 12, 45, 78, 65, 58, 62, 70, 68, 72, 80, 85, 90, 88, 75, 60, 45, 30, 18],
            borderColor: '#4FC3F7',
            backgroundColor: 'rgba(79, 195, 247, 0.15)',
            borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          scales: { x: { display: false }, y: { display: false } },
        },
      })
    }
  }

  return (
    <div className="home">
      {/* Hero */}
      <section id="home" className="hero">
        <div className="hero-content">
          <div className="hero-badge">
            <span className="badge-dot" />
            <span>Powered by Multi-Agent Architecture</span>
          </div>
          <h1 className="hero-title">
            让 <span className="gradient-text">数学建模</span>
            <br />
            变得 <span className="typing-text">{typed}</span><span className="cursor">|</span>
          </h1>
          <p className="hero-subtitle">
            融合大语言模型、符号计算与数值仿真的一体化建模平台<br />
            从题目理解到论文撰写，全流程智能辅助
          </p>
          <div className="hero-actions">
            <button className="btn-primary large" onClick={onStart}>
              <span>开始建模</span>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>

        <div className="hero-visual">
          <div className="float-card card-1">
            <div className="card-header">
              <span className="card-tag">优化模型</span>
              <span className="card-time">2.3s</span>
            </div>
            <div className="math-formula" ref={formulaRef} />
          </div>
          <div className="float-card card-2">
            <div className="card-header">
              <span className="card-tag green">预测模型</span>
            </div>
            <div className="chart-mini">
              <canvas ref={miniRef} width="200" height="80" />
            </div>
          </div>
          <div className="float-card card-3">
            <div className="code-block">
              <span className="code-line"><span className="kw">def</span> <span className="fn">solve_lp</span>():</span>
              <span className="code-line">    <span className="cmt"># 线性规划求解</span></span>
              <span className="code-line">    <span className="fn">result</span> = linprog(c, A_ub, b_ub)</span>
              <span className="code-line">    <span className="kw">return</span> result.x</span>
            </div>
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section id="capabilities" className="section">
        <div className="section-header">
          <div className="section-tag">CORE CAPABILITIES</div>
          <h2 className="section-title">六大核心建模能力</h2>
          <p className="section-subtitle">覆盖数学建模全流程，从问题分析到论文产出</p>
        </div>
        <div className="capabilities-grid">
          {CAPABILITIES.map((c) => (
            <div className="cap-card" key={c.title}>
              <div className="cap-icon">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d={c.icon} />
                </svg>
              </div>
              <h3>{c.title}</h3>
              <p>{c.desc}</p>
              <div className="cap-tag">{c.tag}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Workflow */}
      <section id="workflow" className="section section-alt">
        <div className="section-header">
          <div className="section-tag">WORKFLOW</div>
          <h2 className="section-title">六步建模工作流</h2>
          <p className="section-subtitle">从赛题发布到论文提交，智能化全流程辅助</p>
        </div>
        <div className="workflow">
          <div className="workflow-line" />
          <div className="workflow-steps">
            {WORKFLOW.map((w) => (
              <div className="wf-step" key={w.n}>
                <div className="wf-num">{w.n}</div>
                <h3>{w.t}</h3>
                <p>{w.d}</p>
                <div className="wf-duration">{w.dur}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="cta">
        <div className="cta-bg"><div className="cta-glow" /></div>
        <div className="cta-content">
          <h2>准备好开始你的<br /><span className="gradient-text">建模之旅</span>了吗？</h2>
          <div className="cta-actions">
            <button className="btn-primary large" onClick={onStart}>免费开始使用</button>
            <button
              className="btn-ghost large"
              onClick={onDocs}
            >
              查看文档
            </button>
          </div>
        </div>
      </section>

      </div>
  )
}
