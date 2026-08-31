export const OPEN_CHANGES_PANEL_EVENT = 'deepseekgui:open-changes-panel'

export type ChangeReviewContext = 'working-tree' | 'last-turn' | 'project' | 'conflicts'

export type ChangeReviewRequest = {
  context?: ChangeReviewContext
  turnId?: string
  path?: string
  workspaceRoot?: string
}

export function normalizeChangeReviewRequest(
  detail: ChangeReviewRequest | null | undefined
): Required<Pick<ChangeReviewRequest, 'context'>> & Omit<ChangeReviewRequest, 'context'> {
  const context =
    detail?.context === 'working-tree' ||
    detail?.context === 'last-turn' ||
    detail?.context === 'project' ||
    detail?.context === 'conflicts'
      ? detail.context
      : 'working-tree'
  const turnId = detail?.turnId?.trim() || undefined
  const path = detail?.path?.trim() || undefined
  const workspaceRoot = detail?.workspaceRoot?.trim() || undefined
  return { context, turnId, path, workspaceRoot }
}

export function openChangesPanel(detail: ChangeReviewRequest = {}): void {
  window.dispatchEvent(
    new CustomEvent<ChangeReviewRequest>(OPEN_CHANGES_PANEL_EVENT, { detail })
  )
}
