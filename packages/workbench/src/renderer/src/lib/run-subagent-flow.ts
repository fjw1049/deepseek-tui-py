import type { ChatBlock } from '../agent/types'
import { humanizeAgentType } from './agent-type-label'
import { subagentStepsToFlowItems } from './subagent-mailbox'
import { lifecycleToStepStatus, type StepFlowItem } from '../components/chat/StepFlow'
export type SubagentBlock = Extract<ChatBlock, { kind: 'subagent' }>

type SubagentTreeNode = {
  id: string
  label: string
  status: SubagentBlock['status']
  depth: number
}

export function buildSubagentTreeNodes(
  root: SubagentBlock,
  related: SubagentBlock[]
): SubagentTreeNode[] {
  const byId = new Map<string, SubagentBlock>()
  for (const b of related) byId.set(b.agentId, b)
  byId.set(root.agentId, root)

  const nodes: SubagentTreeNode[] = []
  const seen = new Set<string>()

  const visit = (id: string, depth: number): void => {
    if (seen.has(id)) return
    seen.add(id)
    const block = byId.get(id)
    if (block) {
      nodes.push({
        id,
        label:
          block.cardKind === 'fanout'
            ? `${humanizeAgentType(block.agentType)} · fanout`
            : humanizeAgentType(block.agentType),
        status: block.status,
        depth
      })
      if (block.cardKind === 'fanout') {
        for (const worker of block.workers ?? []) {
          if (byId.has(worker.id)) {
            visit(worker.id, depth + 1)
          } else {
            nodes.push({
              id: worker.id,
              label: `worker`,
              status: worker.status,
              depth: depth + 1
            })
          }
        }
      }
      for (const childId of block.childIds ?? []) {
        visit(childId, depth + 1)
      }
      return
    }
    nodes.push({
      id,
      label: 'agent',
      status: 'pending',
      depth
    })
  }

  visit(root.agentId, 0)
  return nodes
}

export function resolveSubagentFlowItems(
  root: SubagentBlock,
  related: SubagentBlock[],
  selectedId: string
): StepFlowItem[] {
  const byId = new Map<string, SubagentBlock>()
  for (const b of related) byId.set(b.agentId, b)
  byId.set(root.agentId, root)

  const selected = byId.get(selectedId)
  if (selected) {
    if (selected.cardKind === 'fanout' && selectedId === selected.agentId) {
      // Root fanout: concatenate worker rails with indent.
      const items: StepFlowItem[] = [
        {
          id: `${selected.agentId}-root`,
          status: lifecycleToStepStatus(selected.status),
          label: `${humanizeAgentType(selected.agentType)} · ${selected.status}`,
          depth: 0
        }
      ]
      for (const worker of selected.workers ?? []) {
        items.push({
          id: `${worker.id}-head`,
          status: lifecycleToStepStatus(worker.status),
          label: `worker ${worker.id.slice(0, 8)} · ${worker.status}`,
          depth: 1
        })
        items.push(
          ...subagentStepsToFlowItems(selected.workerSteps?.[worker.id], 2, worker.status)
        )
      }
      return items
    }
    return subagentStepsToFlowItems(selected.steps, 0, selected.status)
  }

  // A nested fanout worker may live on a descendant card rather than the root.
  const owner = [...byId.values()].find((block) => block.workers?.some((worker) => worker.id === selectedId))
  if (owner) {
    return subagentStepsToFlowItems(owner.workerSteps?.[selectedId], 0, owner.workers?.find((worker) => worker.id === selectedId)?.status)
  }
  return []
}

