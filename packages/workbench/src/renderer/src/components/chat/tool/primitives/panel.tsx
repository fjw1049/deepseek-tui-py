import { cn } from '../cn'

/** Padded body wrapper for tool output. */
export function ToolBody({
  children,
  className
}: {
  children: React.ReactNode
  className?: string
}): React.JSX.Element {
  return <div className={cn('space-y-1.5 px-3 pb-2.5 pt-1', className)}>{children}</div>
}

/** Error banner shown when a tool fails. */
export function ToolErrorState({
  message,
  className
}: {
  message: string
  className?: string
}): React.JSX.Element {
  return (
    <div
      className={cn(
        'overflow-hidden rounded-[10px] border border-red-200/80 bg-red-50/80 px-3 py-2 text-[12px] leading-5 text-red-700 dark:border-red-800/40 dark:bg-red-500/10 dark:text-red-300',
        className
      )}
    >
      {message}
    </div>
  )
}

/** Neutral placeholder when a tool produced no output. */
export function ToolEmptyState({
  message,
  className
}: {
  message: string
  className?: string
}): React.JSX.Element {
  return (
    <div className={cn('px-3 py-2 text-[12px] text-ds-faint', className)}>{message}</div>
  )
}
