import type { ChatBlock } from '../agent/types'

export type DockSubagentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type DockSubagentItem = {
  id: string
  agentId: string
  agentType: string
  status: DockSubagentStatus
}

export function isActiveSubagentStatus(status: DockSubagentStatus): boolean {
  return status === 'pending' || status === 'running'
}

/** Conversation subagent cards for the operation dock (display-only). */
export function extractSubagentsFromBlocks(blocks: ChatBlock[]): DockSubagentItem[] {
  const out: DockSubagentItem[] = []
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    out.push({
      id: block.id,
      agentId: block.agentId,
      agentType: block.agentType,
      status: block.status
    })
  }
  return out
}
