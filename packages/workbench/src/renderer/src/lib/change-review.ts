export const OPEN_CHANGES_PANEL_EVENT = 'deepseekgui:open-changes-panel'

export type ChangeReviewContext =
  | 'working-tree'
  | 'staged'
  | 'unstaged'
  | 'branch'
  | 'all-turns'
  | 'last-turn'
  | 'conflicts'

export type ChangeReviewRequest = {
  /** `project` is accepted only as a backwards-compatible navigation alias. */
  context?: ChangeReviewContext | 'project'
  turnId?: string
  path?: string
  workspaceRoot?: string
}

export type NormalizedChangeReviewRequest = Omit<ChangeReviewRequest, 'context'> & {
  context: ChangeReviewContext
}

export function normalizeChangeReviewRequest(
  detail: ChangeReviewRequest | null | undefined
): NormalizedChangeReviewRequest {
  const requested = detail?.context
  const context: ChangeReviewContext =
    requested === 'project'
      ? 'working-tree'
      : requested === 'working-tree' ||
        requested === 'staged' ||
    requested === 'unstaged' ||
    requested === 'branch' ||
    requested === 'all-turns' ||
    requested === 'last-turn' ||
    requested === 'conflicts'
      ? requested
      : 'branch'
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
