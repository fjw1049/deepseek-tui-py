const AGENT_TYPE_LABELS: Record<string, string> = {
  custom: '自定义',
  explore: '探索',
  general: '通用',
  implementer: '实现',
  plan: '规划',
  review: '审查',
  verifier: '验证',
  rlm: '并行',
  fanout: '并行',
  swarm: '并行',
  agent_swarm: '并行'
}

/** Localize known sub-agent type ids for UI chrome (explore → 探索). */
export function humanizeAgentType(type: string | null | undefined): string {
  const raw = (type || '').trim()
  if (!raw) return ''
  return AGENT_TYPE_LABELS[raw.toLowerCase()] ?? raw
}
