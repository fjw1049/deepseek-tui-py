type InspectorSelectionInput = {
  fileIds: readonly string[]
  selectedId: string | null
  loading: boolean
  passive: boolean
}

/**
 * Returns the selection to write, or `undefined` when this inspector should
 * leave the shared selection alone. The IDE diff is passive because its file
 * list loads independently from the activity-sidebar list.
 */
export function resolveInspectorSelectionUpdate({
  fileIds,
  selectedId,
  loading,
  passive
}: InspectorSelectionInput): string | null | undefined {
  if (selectedId !== null && fileIds.includes(selectedId)) return undefined
  if (loading) return undefined
  if (passive && selectedId !== null) return undefined

  const fallbackId = fileIds[fileIds.length - 1]
  if (fallbackId) return fallbackId
  return selectedId === null || passive ? undefined : null
}
