import type { ReactElement } from 'react'

/** Indented pulse bars — loading chrome for the editor/search/tree, not a spinner. */
export function EditorListSkeleton({ rows = 7 }: { rows?: number }): ReactElement {
  return (
    <div className="ds-editor-skeleton flex min-h-0 flex-1 flex-col gap-2 px-3 py-4" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="ds-editor-skeleton__bar h-2.5 rounded-sm"
          style={{
            width: `${78 - (index % 4) * 10}%`,
            marginLeft: index % 3 === 1 ? 14 : index % 3 === 2 ? 28 : 0
          }}
        />
      ))}
    </div>
  )
}
