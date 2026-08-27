import type { ChatBlock, ToolBlock } from '../agent/types'

export type ApprovalGate = Extract<ChatBlock, { kind: 'approval' }>
export type ElevationGate = Extract<ChatBlock, { kind: 'elevation' }>

export type PendingToolGate = {
  approval: ApprovalGate | null
  elevation: ElevationGate | null
}

/** Ids that an approval/elevation payload may use to point at this tool row. */
export function toolGateIds(block: ToolBlock): string[] {
  const ids = new Set<string>()
  if (block.id.trim()) ids.add(block.id.trim())
  const callId = block.meta?.tool_call_id
  if (typeof callId === 'string' && callId.trim()) ids.add(callId.trim())
  return [...ids]
}

export function findPendingToolGate(
  blocks: readonly ChatBlock[],
  tool: ToolBlock
): PendingToolGate {
  const ids = new Set(toolGateIds(tool))
  let approval: ApprovalGate | null = null
  let elevation: ElevationGate | null = null
  for (const block of blocks) {
    if (block.kind === 'approval' && block.status === 'pending' && ids.has(block.approvalId)) {
      approval = block
    }
    if (block.kind === 'elevation' && block.status === 'pending' && ids.has(block.elevationId)) {
      elevation = block
    }
  }
  return { approval, elevation }
}

export function hasPendingToolGate(gate: PendingToolGate): boolean {
  return gate.approval != null || gate.elevation != null
}
