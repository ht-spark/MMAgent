import { useEffect, useRef, useState } from 'react'

type Props = { onStart: () => void }

const STATS = [
  { target: 12847, label: '已解决问题', pct: false },
  { target: 386, label: '获奖案例', pct: false },
  { target: 156, label: '内置模型', pct: false },
  { target: 98, label: '% 满意度', pct: true },
]

const CAPABILITIES = [
  { icon: 'M21 21l-4.35-4.35M11 19a8 8 0 100-16 8 8 0 000 16zM3 9h18M9 21V9', title: '题目解析', desc: '深度理解赛题背景，自动提取关键信息，识别问题类型与约束条件', tag: 'NLP · 知识图谱' },
  { icon: 'M3 3h18v18H3zM3 9h18M9 21V9', title: '模型选择', desc: '基于问题特征智能推荐最优建模方法，覆盖 156+ 经典模型', tag: '决策树 · 匹配算法' },
  { icon: 'M16 18l6-6-6-6M8 6l-6 6 6 6', title: '代码生成', desc: '自动生成 Python / MATLAB 代码，集成 SciPy、PuLP、Gurobi 等工具链', tag: 'Code-LLM · 沙箱执行' },
  { icon: 'M3 3v18h18M7 14l4-4 4 4 6-6', title: '数据可视化', desc: '自动绘制专业级图表，论文级排版，支持 LaTeX 公式嵌入', tag: 'Matplotlib · D3.js' },
  { icon: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2', title: '结果分析', desc: '灵敏度分析、误差评估、模型对比，确保结论科学严谨', tag: '统计分析 · 蒙特卡洛' },
  { icon: 'M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8', title: '论文撰写', desc: '一键生成结构化建模论文，含摘要、模型、求解、结论完整章节', tag: 'LaTeX · 学术规范' },
]

const MODELS = [
  { icon: '⚡', title: '优化模型', items: ['线性规划 (LP)', '整数规划 (IP)', '非线性规划 (NLP)', '动态规划 (DP)', '多目标优化', '遗传算法'], count: '28 个模型' },
  { icon: '📈', title: '预测模型', items: ['时间序列 ARIMA', 'LSTM 神经网络', 'Prophet 预测', '灰色预测 GM(1,1)', '贝叶斯预测', 'XGBoost 回归'], count: '35 个模型' },
  { icon: '🎯', title: '评价模型', items: ['层次分析法 (AHP)', 'TOPSIS 综合评价', '熵权法', '模糊综合评价', '主成分分析 (PCA)', '数据包络 (DEA)'], count: '24 个模型' },
  { icon: '📊', title: '统计模型', items: ['多元回归分析', '方差分析 (ANOVA)', '聚类分析 (K-means)', '判别分析', '贝叶斯统计', '蒙特卡洛模拟'], count: '31 个模型' },
  { icon: '🕸️', title: '图论模型', items: ['最短路径 (Dijkstra)', '最小生成树', '网络流', '匹配问题', '图着色', '复杂网络'], count: '19 个模型' },
  { icon: '∫', title: '微分方程', items: ['常微分方程 (ODE)', '偏微分方程 (PDE)', '差分方程', '传染病模型 (SIR)', '种群动力学', '反应扩散方程'], count: '19 个模型' },
]

const WORKFLOW = [
  { n: '01', t: '题目理解', d: '自动解析赛题，提取关键信息', dur: '~30s' },
  { n: '02', t: '思路分析', d: '多方案对比，确定建模路径', dur: '~2min' },
  { n: '03', t: '模型建立', d: '选择并构建数学模型', dur: '~5min' },
  { n: '04', t: '算法实现', d: '代码生成与运行验证', dur: '~3min' },
  { n: '05', t: '结果分析', d: '可视化与误差评估', dur: '~2min' },
  { n: '06', t: '论文撰写', d: '一键生成完整论文', dur: '~8min' },
]

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string),
  )
}

function generateResponse(input: string): string {
  if (input.includes('预测') || input.includes('forecast')) {
    return `<div class="msg-text">已为你选择 <strong>SARIMA + LSTM</strong> 组合预测模型，预测精度可达 <strong>94.7%</strong>。已生成代码与可视化结果。</div>`
  }
  if (input.includes('优化') || input.includes('规划')) {
    return `<div class="msg-text">推荐使用 <strong>线性规划/整数规划</strong>，已生成求解代码。可在「代码」标签页查看。</div>`
  }
  if (input.includes('评价') || input.includes('排名')) {
    return `<div class="msg-text">建议采用 <strong>层次分析法 (AHP) + 熵权法</strong> 组合评价，权重更客观。已生成完整方案。</div>`
  }
  return `<div class="msg-text">正在分析你的问题...<br>已识别为综合建模任务，将自动选择最优算法组合进行求解。</div>`
}

export default function Home({ onStart }: Props) {
  const [typed, setTyped] = useState('')
  const [activeTab, setActiveTab] = useState('chart')
  const [messages, setMessages] = useState<
    { role: 'user' | 'agent'; text: string; time: string }[]
  >([
    { role: 'agent', text: '你好！我是 ModelForge 数学建模智能体。我可以帮你完成从题目分析到论文撰写的全流程工作。', time: '15:02:17' },
    { role: 'user', text: '请帮我分析这道题：某城市交通流量预测，已知过去 30 天每小时的车流量数据，请建立预测模型。', time: '15:02:34' },
    { role: 'agent', text: '好的，这是一个典型的时间序列预测问题。我建议采用 SARIMA + LSTM 组合模型，并给出 MAE / RMSE / MAPE 评估指标。', time: '15:02:41' },
  ])
  const [input, setInput] = useState('')

  const formulaRef = useRef<HTMLDivElement>(null)
  const miniRef = useRef<HTMLCanvasElement>(null)
  const forecastRef = useRef<HTMLCanvasElement>(null)
  const chatMessagesRef = useRef<HTMLDivElement>(null)

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

  /* Counters */
  useEffect(() => {
    const els = Array.from(document.querySelectorAll('.stat-num')) as HTMLElement[]
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          const el = e.target as HTMLElement
          const target = parseInt(el.dataset.target || '0', 10)
          const isPct = el.nextElementSibling?.textContent?.includes('满意度')
          const start = performance.now()
          const step = (now: number) => {
            const t = Math.min((now - start) / 1500, 1)
            const v = Math.floor(target * (1 - Math.pow(1 - t, 3)))
            el.textContent = isPct ? v + '%' : v.toLocaleString()
            if (t < 1) requestAnimationFrame(step)
            else el.textContent = isPct ? target + '%' : target.toLocaleString()
          }
          requestAnimationFrame(step)
          obs.unobserve(el)
        }
      })
    }, { threshold: 0.5 })
    els.forEach((el) => obs.observe(el))
    return () => obs.disconnect()
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
      if (w.Chart && miniRef.current && forecastRef.current) {
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
    if (forecastRef.current) {
      const actual: number[] = []
      const predicted: (number | null)[] = []
      for (let i = 0; i < 48; i++) {
        const base = 500 + 1500 * Math.sin((i / 24) * Math.PI * 2 - Math.PI / 2) + Math.random() * 100
        actual.push(Math.max(0, base))
        predicted.push(i < 24 ? null : Math.max(0, base + (Math.random() * 80 - 40)))
      }
      new Chart(forecastRef.current.getContext('2d'), {
        type: 'line',
        data: {
          labels: Array.from({ length: 48 }, (_, i) => `${i % 24}:00`),
          datasets: [
            { label: '实际值', data: actual, borderColor: '#0288D1', backgroundColor: 'rgba(2,136,209,0.1)', borderWidth: 2, fill: true, tension: 0.4, pointRadius: 0 },
            { label: '预测值', data: predicted, borderColor: '#00E5FF', backgroundColor: 'rgba(0,229,255,0.1)', borderWidth: 2, borderDash: [5, 4], fill: true, tension: 0.4, pointRadius: 0 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top', align: 'end', labels: { usePointStyle: true, pointStyle: 'circle', font: { size: 12 }, color: '#243B53' } },
            tooltip: { backgroundColor: 'rgba(13,27,42,0.95)', titleColor: '#B3E5FC', bodyColor: '#fff', borderColor: '#4FC3F7', borderWidth: 1, padding: 10, cornerRadius: 8 },
          },
          scales: {
            x: { grid: { color: 'rgba(3,169,244,0.06)' }, ticks: { color: '#829AB1', font: { size: 10 } } },
            y: { grid: { color: 'rgba(3,169,244,0.06)' }, ticks: { color: '#829AB1', font: { size: 10 } } },
          },
        },
      })
    }
  }

  function send() {
    const text = input.trim()
    if (!text) return
    const time = new Date().toTimeString().slice(0, 8)
    setMessages((m) => [...m, { role: 'user', text, time }])
    setInput('')
    setTimeout(() => {
      setMessages((m) => [...m, { role: 'agent', text: generateResponse(text), time: new Date().toTimeString().slice(0, 8) }])
    }, 800)
  }

  useEffect(() => {
    const c = chatMessagesRef.current
    if (c) c.scrollTop = c.scrollHeight
  }, [messages])

  function scrollToDemo() {
    document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' })
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
            <button className="btn-ghost large" onClick={scrollToDemo}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M4 4l8 4-8 4V4z" fill="currentColor" />
              </svg>
              <span>观看演示</span>
            </button>
          </div>
          <div className="hero-stats">
            {STATS.map((s) => (
              <div className="stat" key={s.label}>
                <div className="stat-num" data-target={s.target}>0</div>
                <div className="stat-label">{s.label}</div>
              </div>
            ))}
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

      {/* Demo */}
      <section id="demo" className="section section-alt">
        <div className="section-header">
          <div className="section-tag">INTERACTIVE DEMO</div>
          <h2 className="section-title">与智能体实时对话</h2>
          <p className="section-subtitle">输入建模问题，查看智能体分析过程与结果</p>
        </div>
        <div className="demo-container">
          <div className="chat-panel">
            <div className="panel-header">
              <div className="panel-title">
                <span className="status-dot" />
                <span>ModelForge Agent</span>
              </div>
            </div>
            <div className="chat-messages" ref={chatMessagesRef}>
              {messages.map((m, i) => (
                <div className={`message ${m.role}`} key={i}>
                  {m.role === 'agent' && <div className="msg-avatar">M</div>}
                  <div className="msg-content">
                    <div className="msg-text" dangerouslySetInnerHTML={{ __html: m.text }} />
                    <div className="msg-time">{m.time}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="chat-input">
              <input
                type="text"
                value={input}
                placeholder="输入你的建模问题..."
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && send()}
              />
              <button className="send-btn" onClick={send}>
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path d="M2 9l14-7-5 7 5 7-14-7z" fill="currentColor" />
                </svg>
              </button>
            </div>
          </div>

          <div className="result-panel">
            <div className="panel-header">
              <div className="panel-title">
                <span>实时结果</span>
                <span className="panel-tag">v2.4.1</span>
              </div>
            </div>
            <div className="result-tabs">
              <button className={`tab ${activeTab === 'chart' ? 'active' : ''}`} onClick={() => setActiveTab('chart')}>预测图表</button>
              <button className={`tab ${activeTab === 'code' ? 'active' : ''}`} onClick={() => setActiveTab('code')}>代码</button>
              <button className={`tab ${activeTab === 'data' ? 'active' : ''}`} onClick={() => setActiveTab('data')}>数据</button>
            </div>
            <div className="result-content">
              <div className={`tab-pane ${activeTab === 'chart' ? 'active' : ''}`}>
                <div className="result-chart">
                  <canvas ref={forecastRef} />
                </div>
                <div className="result-meta">
                  <div className="meta-item"><span className="meta-label">预测精度</span><span className="meta-val">94.7%</span></div>
                  <div className="meta-item"><span className="meta-label">RMSE</span><span className="meta-val">12.34</span></div>
                  <div className="meta-item"><span className="meta-label">MAE</span><span className="meta-val">8.91</span></div>
                </div>
              </div>
              <div className={`tab-pane ${activeTab === 'code' ? 'active' : ''}`}>
                <pre className="code-display"><span className="kw">import</span> numpy <span className="kw">as</span> np
<span className="kw">from</span> statsmodels.tsa.statespace.sarimax <span className="kw">import</span> SARIMAX

<span className="cmt"># 数据准备</span>
scaler = MinMaxScaler()
scaled_data = scaler.<span className="fn">fit_transform</span>(traffic_data)

<span className="cmt"># SARIMA 模型</span>
sarima_model = <span className="fn">SARIMAX</span>(traffic_data, order=(<span className="num">2</span>,<span className="num">1</span>,<span className="num">2</span>), seasonal_order=(<span className="num">1</span>,<span className="num">1</span>,<span className="num">1</span>,<span className="num">24</span>))
results = sarima_model.<span className="fn">fit</span>()
forecast = results.<span className="fn">forecast</span>(steps=<span className="num">168</span>)</pre>
              </div>
              <div className={`tab-pane ${activeTab === 'data' ? 'active' : ''}`}>
                <table className="data-table">
                  <thead>
                    <tr><th>时间</th><th>实际值</th><th>预测值</th><th>误差</th></tr>
                  </thead>
                  <tbody>
                    <tr><td>00:00</td><td>234</td><td>241</td><td className="err-low">+3.0%</td></tr>
                    <tr><td>06:00</td><td>1,247</td><td>1,289</td><td className="err-low">+3.4%</td></tr>
                    <tr><td>12:00</td><td>2,156</td><td>2,098</td><td className="err-high">-2.7%</td></tr>
                    <tr><td>18:00</td><td>1,876</td><td>1,852</td><td className="err-high">-1.3%</td></tr>
                    <tr><td>23:00</td><td>456</td><td>461</td><td className="err-low">+1.1%</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Models */}
      <section id="models" className="section">
        <div className="section-header">
          <div className="section-tag">MODEL LIBRARY</div>
          <h2 className="section-title">156+ 经典模型库</h2>
          <p className="section-subtitle">覆盖数学建模竞赛全部主流题型与方法</p>
        </div>
        <div className="models-grid">
          {MODELS.map((m) => (
            <div className="model-category" key={m.title}>
              <div className="cat-icon">{m.icon}</div>
              <h3>{m.title}</h3>
              <ul className="model-list">
                {m.items.map((it) => (
                  <li key={it}>{it}</li>
                ))}
              </ul>
              <div className="model-count">{m.count}</div>
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
          <p>加入 12,000+ 建模爱好者，体验 AI 驱动的建模新范式</p>
          <div className="cta-actions">
            <button className="btn-primary large" onClick={onStart}>免费开始使用</button>
            <button className="btn-ghost large" onClick={onStart}>查看文档</button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-col">
            <div className="logo">
              <div className="logo-icon">
                <svg viewBox="0 0 32 32" width="24" height="24">
                  <path d="M4 24 L4 8 L10 8 L16 16 L22 8 L28 8 L28 24 L24 24 L24 14 L18 22 L14 22 L8 14 L8 24 Z" fill="url(#sidebarLogoGrad)" />
                </svg>
              </div>
              <div className="logo-text"><span className="logo-name">ModelForge</span></div>
            </div>
            <p className="footer-desc">让数学建模更简单，让建模竞赛更有趣。</p>
          </div>
          <div className="footer-col"><h4>产品</h4><ul><li><a href="#">智能体平台</a></li><li><a href="#">模型库</a></li><li><a href="#">代码沙箱</a></li><li><a href="#">论文模板</a></li></ul></div>
          <div className="footer-col"><h4>资源</h4><ul><li><a href="#">建模教程</a></li><li><a href="#">案例库</a></li><li><a href="#">API 文档</a></li><li><a href="#">社区论坛</a></li></ul></div>
          <div className="footer-col"><h4>关于</h4><ul><li><a href="#">关于我们</a></li><li><a href="#">联系我们</a></li><li><a href="#">加入我们</a></li><li><a href="#">隐私政策</a></li></ul></div>
        </div>
        <div className="footer-bottom">
          <span>© 2026 ModelForge. All rights reserved.</span>
          <span>Built with 💙 for Math Modeling</span>
        </div>
      </footer>
    </div>
  )
}
