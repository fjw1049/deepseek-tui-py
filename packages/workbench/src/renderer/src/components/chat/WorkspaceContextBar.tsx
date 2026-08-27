import { useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { GitBranchPicker } from './GitBranchPicker'
import { ProjectContextPicker } from './ProjectContextPicker'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import {
  workspaceContextBarPlanForWidth,
  workspaceContextBarTierForWidth
} from '../../lib/workspace-context-bar-layout'

type Props = {
  workspaceRoot: string
  /** `tray` tucks under the composer card (home + conversation). `embedded` is IDE compact only. */
  variant?: 'tray' | 'embedded'
}

/** Project / branch row under the composer. Isolation is not a user control. */
export function WorkspaceContextBar({ workspaceRoot, variant = 'tray' }: Props): ReactElement {
  const barRef = useRef<HTMLDivElement>(null)
  const [barWidth, setBarWidth] = useState<number | null>(null)
  const plan = useMemo(() => workspaceContextBarPlanForWidth(barWidth), [barWidth])
  const tier = workspaceContextBarTierForWidth(barWidth)
  const normalizedRoot = normalizeWorkspaceRoot(workspaceRoot)
  const isTemporary = isChatsWorkspace(workspaceRoot) || !normalizedRoot
  const showBranch = Boolean(normalizedRoot) && !isTemporary && plan.showBranch
  const embedded = variant === 'embedded'

  useLayoutEffect(() => {
    const el = barRef.current
    if (!el || typeof ResizeObserver === 'undefined') return

    let frame = 0
    const apply = (width: number): void => {
      setBarWidth((prev) => (prev === width ? prev : width))
    }
    apply(el.getBoundingClientRect().width)

    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry?.contentRect.width ?? el.getBoundingClientRect().width
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => apply(nextWidth))
    })
    observer.observe(el)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  return (
    <div
      ref={barRef}
      className={
        embedded
          ? 'ds-workspace-context-bar ds-workspace-context-bar--embedded relative flex min-h-7 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden px-1 pb-0.5 pt-1'
          : 'ds-workspace-context-bar relative z-0 -mt-5 flex min-h-8 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden rounded-b-[1.2rem] rounded-t-none px-2.5 pb-2 pt-6 sm:px-3.5'
      }
      data-workspace-context-bar="true"
      data-context-bar-variant={variant}
      data-context-bar-tier={barWidth == null ? 'unknown' : String(tier)}
    >
      <div className="ds-workspace-context-project min-w-0 shrink">
        <ProjectContextPicker
          workspaceRoot={workspaceRoot}
          usePortal
          menuPlacement="above"
          hideChevron={!plan.showProjectChevron}
          size={embedded ? 'dense' : 'tray'}
        />
      </div>
      {showBranch ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          <div className="ds-workspace-context-branch min-w-0 shrink">
            <GitBranchPicker
              key={normalizedRoot}
              workspaceRoot={normalizedRoot}
              compact
              size={embedded ? 'dense' : 'tray'}
              usePortal
              menuPlacement="above"
              hideLabel={!plan.showBranchLabel}
              hideChevron={!plan.showBranchChevron}
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
