export const NODE_CN: Record<string, string> = {
  intake: '数据摄入',
  context: '任务理解',
  g0_retry: '任务理解重试',
  g0_clarification: '等待人工澄清',
  select_question: '选择子任务',
  assemble_context: '装配上下文',
  configure_question_budget: '预算配置',
  configure_delivery_budget: '交付预算配置',
  solve_question: '子任务求解',
  validate_result: '结果验证',
  gq_check: '质量检查',
  archive_result: '归档结果',
  global_review: '全局审查',
  write_paper: '报告写作',
  review_paper: '报告审查',
  deliver: '最终交付',
  gf_revise: '报告修订',
}

export const STATUS_CN: Record<string, string> = {
  initializing: '初始化中',
  intake_ready: '数据摄入完成',
  context_ready: '任务理解完成',
  solving: '求解中',
  all_questions_done: '所有子任务完成',
  delivered: '已交付',
  failed: '失败',
}

export const ACTION_CN: Record<string, string> = {
  pass: '通过',
  retry: '重试',
  blocked: '阻塞',
}

export function fmtQid(qid: string): string {
  const m = qid.match(/q(\d+)/i)
  return m ? `第${m[1]}个子任务` : qid
}

export function formatCurrentStep(ev: any, fallbackQuestionId = ''): string {
  const node = ev?.node || 'step'
  const nodeCn = NODE_CN[node] || node
  const qid = ev?.current_question_id || fallbackQuestionId
  if (node === 'select_question' && qid) {
    return `${nodeCn} · 求解中 [${fmtQid(qid)}]`
  }
  return nodeCn
}

export function formatProgressLine(ev: any, fallbackQuestionId = ''): string | null {
  if (!ev || typeof ev !== 'object') return null

  if (ev.type === 'budget_confirmed') {
    const action = ev.action
    const scope = ev.phase === 'initial'
        ? '输入信息质量检查预算'
      : ev.phase === 'delivery'
        ? '最后交付前质量检查预算'
        : `子任务预算 · ${fmtQid(ev.question_id || fallbackQuestionId || '')}`
    if (action === 'override') return `${scope}已按输入覆盖`
    if (action === 'default') return `${scope}沿用默认`
    return `${scope}确认已取消`
  }

  if (ev.type === 'clarification_resolved') {
    if (ev.action === 'terminate') return '用户选择终止建模（材料不足）'
    if (ev.action === 'continue') return '用户上传补充材料，继续建模'
    return '人工澄清已取消'
  }

  if (ev.type !== 'node') return null

  const node = ev.node || 'step'
  if (node === 'configure_question_budget' || node === 'configure_delivery_budget') return null
  if (node === 'context' && ev.workflow_status === 'context_ready') {
    const questionCount = Number(ev.question_count)
    const suffix = Number.isFinite(questionCount) && questionCount > 0
      ? ` · 共${questionCount}个子任务`
      : ''
    return `任务理解 · 任务理解完成${suffix}`
  }
  if (node === 'select_question' && ev.workflow_status === 'all_questions_done') {
    return '所有子任务完成'
  }
  if (node === 'deliver') return '最终交付'

  const nodeCn = NODE_CN[node] || node
  const wf = ev.workflow_status || ''
  const gqAction = ev.gq_action || ''
  const parts: string[] = [nodeCn]

  if (wf) parts.push(STATUS_CN[wf] || wf)
  if (gqAction) parts.push(`（${ACTION_CN[gqAction] || gqAction}）`)

  const qid = ev.current_question_id || fallbackQuestionId
  const qidSuffix = node === 'select_question' && qid && wf === 'solving'
    ? ` [${fmtQid(qid)}]`
    : ''
  return parts.join(' · ') + qidSuffix
}

export function nextProgressQuestionId(ev: any, currentQuestionId = ''): string {
  if (!ev || typeof ev !== 'object') return currentQuestionId
  if (ev.type === 'budget_request' && ev.phase === 'question' && ev.question_id) {
    return ev.question_id
  }
  if (ev.type === 'budget_confirmed' && ev.phase === 'question' && ev.question_id) {
    return ev.question_id
  }
  if (ev.type === 'node' && ev.node === 'select_question' && ev.workflow_status === 'all_questions_done') {
    return ''
  }
  if (typeof ev.current_question_id === 'string') {
    if (ev.current_question_id) return ev.current_question_id
    if (ev.type === 'node' && ev.node === 'archive_result') return ''
  }
  return currentQuestionId
}
