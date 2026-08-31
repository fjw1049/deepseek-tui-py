export const OPEN_CHANGES_PANEL_EVENT = 'deepseekgui:open-changes-panel'

export type ChangeReviewScope = 'turn' | 'thread' | 'workspace' | 'conflicts'

export type ChangeReviewRequest = {
  scope?: ChangeReviewScope
  turnId?: string
  path?: string
}

export function normalizeChangeReviewRequest(
  detail: ChangeReviewRequest | null | undefined
): Required<Pick<ChangeReviewRequest, 'scope'>> & Omit<ChangeReviewRequest, 'scope'> {
  const scope =
    detail?.scope === 'turn' ||
    detail?.scope === 'thread' ||
    detail?.scope === 'workspace' ||
    detail?.scope === 'conflicts'
      ? detail.scope
      : 'thread'
  const turnId = detail?.turnId?.trim() || undefined
  const path = detail?.path?.trim() || undefined
  return { scope, turnId, path }
}

export function openChangesPanel(detail: ChangeReviewRequest = {}): void {
  window.dispatchEvent(
    new CustomEvent<ChangeReviewRequest>(OPEN_CHANGES_PANEL_EVENT, { detail })
  )
}
