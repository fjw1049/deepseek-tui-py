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

export function buildBranchComparisonOptions({
  currentBranch,
  defaultBranch,
  branches
}: {
  currentBranch: string | null
  defaultBranch: string | null
  branches: string[]
}): {
  current: string | null
  default: string | null
  recent: string[]
  searchable: string[]
} {
  const current = currentBranch?.trim() || null
  const defaultRef = defaultBranch?.trim() || null
  const defaultLocalName = defaultRef?.includes('/')
    ? defaultRef.slice(defaultRef.indexOf('/') + 1)
    : defaultRef
  const uniqueBranches = [...new Set(branches.map((branch) => branch.trim()).filter(Boolean))]
  const remaining = uniqueBranches.filter(
    (branch) => branch !== current && branch !== defaultLocalName
  )
  const defaultOption = defaultRef === current ? null : defaultRef
  return {
    current,
    default: defaultOption,
    recent: remaining.slice(0, 5),
    searchable: [
      ...new Set(
        [current, defaultOption, ...remaining].filter((branch): branch is string => Boolean(branch))
      )
    ]
  }
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
