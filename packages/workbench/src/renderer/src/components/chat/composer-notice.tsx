import type { ReactElement } from 'react'
import type { Notice } from '../extensions/marketplace-shared'

export function ComposerNoticeToast({ notice }: { notice: Notice }): ReactElement {
  const className =
    notice.tone === 'error'
      ? 'border-amber-300/80 bg-amber-50/95 text-amber-950 shadow-sm dark:border-amber-700/60 dark:bg-amber-950/35 dark:text-amber-100'
      : notice.tone === 'success'
        ? 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
        : 'border-ds-border bg-ds-subtle text-ds-muted'
  return (
    <div
      role="status"
      className={`max-w-[min(100%,560px)] rounded-xl border px-3 py-2 text-[12px] leading-5 ${className}`}
    >
      {notice.message}
    </div>
  )
}
