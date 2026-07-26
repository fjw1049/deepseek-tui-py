import type { NormalizedThread } from '../agent/types'
import { workspaceLabelFromPath } from './workspace-label'

export const PROJECT_SORT_MODES = [
  'recent',
  'name_asc',
  'thread_count',
  'created'
] as const

export type ProjectSortMode = (typeof PROJECT_SORT_MODES)[number]

export type ProjectGroup = [string, NormalizedThread[]]

export const PROJECT_SORT_STORAGE_KEY = 'deepseekgui.sidebar.projectSort'

export const DEFAULT_PROJECT_SORT_MODE: ProjectSortMode = 'recent'

export function isProjectSortMode(value: unknown): value is ProjectSortMode {
  return typeof value === 'string' && (PROJECT_SORT_MODES as readonly string[]).includes(value)
}

export function loadProjectSortMode(): ProjectSortMode {
  try {
    const raw = window.localStorage.getItem(PROJECT_SORT_STORAGE_KEY)
    if (isProjectSortMode(raw)) return raw
  } catch {
    /* private window / quota */
  }
  return DEFAULT_PROJECT_SORT_MODE
}

export function persistProjectSortMode(mode: ProjectSortMode): void {
  try {
    window.localStorage.setItem(PROJECT_SORT_STORAGE_KEY, mode)
  } catch {
    /* private window / quota */
  }
}

function latestActivityMs(list: NormalizedThread[]): number {
  if (list.length === 0) return 0
  return Math.max(...list.map((thread) => Date.parse(thread.updatedAt) || 0))
}

/** Earliest thread creation in the group; 0 when unknown / empty (sorts last for created). */
function earliestCreatedMs(list: NormalizedThread[]): number {
  let min = Number.POSITIVE_INFINITY
  for (const thread of list) {
    const raw = thread.createdAt?.trim()
    if (!raw) continue
    const ms = Date.parse(raw)
    if (Number.isFinite(ms) && ms < min) min = ms
  }
  return Number.isFinite(min) ? min : 0
}

function nameTiebreak(pathA: string, pathB: string): number {
  return workspaceLabelFromPath(pathA).localeCompare(workspaceLabelFromPath(pathB))
}

export function compareProjectGroups(
  a: ProjectGroup,
  b: ProjectGroup,
  mode: ProjectSortMode
): number {
  const [pathA, listA] = a
  const [pathB, listB] = b

  switch (mode) {
    case 'recent': {
      const diff = latestActivityMs(listB) - latestActivityMs(listA)
      return diff !== 0 ? diff : nameTiebreak(pathA, pathB)
    }
    case 'name_asc':
      return nameTiebreak(pathA, pathB)
    case 'thread_count': {
      const diff = listB.length - listA.length
      return diff !== 0 ? diff : nameTiebreak(pathA, pathB)
    }
    case 'created': {
      const createdA = earliestCreatedMs(listA)
      const createdB = earliestCreatedMs(listB)
      // Empty / unknown creation → last; otherwise newer first.
      if (createdA === 0 && createdB === 0) return nameTiebreak(pathA, pathB)
      if (createdA === 0) return 1
      if (createdB === 0) return -1
      const diff = createdB - createdA
      return diff !== 0 ? diff : nameTiebreak(pathA, pathB)
    }
    default:
      return nameTiebreak(pathA, pathB)
  }
}

export function sortProjectGroups(
  groups: ProjectGroup[],
  mode: ProjectSortMode
): ProjectGroup[] {
  return [...groups].sort((a, b) => compareProjectGroups(a, b, mode))
}
