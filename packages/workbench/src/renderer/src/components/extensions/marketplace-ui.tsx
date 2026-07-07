import type { ReactElement } from 'react'
import type { Notice } from './marketplace-shared'

export function NoticeView({ notice }: { notice: Notice }): ReactElement {
  const className =
    notice.tone === 'error'
      ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
      : notice.tone === 'success'
        ? 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
        : 'border-ds-border bg-ds-subtle text-ds-muted'
  return (
    <div className={`mt-4 rounded-xl border px-3 py-2 text-[13px] leading-5 ${className}`}>{notice.message}</div>
  )
}
