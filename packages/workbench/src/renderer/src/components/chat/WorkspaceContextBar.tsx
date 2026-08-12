import { useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { Laptop } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import {
  workspaceContextBarPlanForWidth,
  workspaceContextBarTierForWidth
} from '../../lib/workspace-context-bar-layout'
import { GitBranchPicker } from './GitBranchPicker'
import { ProjectContextPicker } from './ProjectContextPicker'

type Props = {
  workspaceRoot: string
}

/** Empty-stage tray tucked under the composer shell. */
export function WorkspaceContextBar({ workspaceRoot }: Props): ReactElement {
  const { t } = useTranslation('common')
  const barRef = useRef<HTMLDivElement>(null)
  const [barWidth, setBarWidth] = useState<number | null>(null)
  const plan = useMemo(() => workspaceContextBarPlanForWidth(barWidth), [barWidth])
  const tier = workspaceContextBarTierForWidth(barWidth)

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

  const normalizedRoot = normalizeWorkspaceRoot(workspaceRoot)
  const isTemporary = isChatsWorkspace(workspaceRoot) || !normalizedRoot
  const showBranch = Boolean(normalizedRoot) && !isTemporary && plan.showBranch

  return (
    <div
      ref={barRef}
      className="ds-workspace-context-bar relative z-0 -mt-5 flex min-h-8 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden rounded-b-[1.2rem] rounded-t-none px-2.5 pb-1.5 pt-6 sm:min-h-7 sm:px-3.5"
      data-workspace-context-bar="true"
      data-context-bar-tier={barWidth == null ? 'unknown' : String(tier)}
    >
      <div className="ds-workspace-context-project min-w-0 shrink">
        <ProjectContextPicker
          workspaceRoot={workspaceRoot}
          usePortal
          menuPlacement="above"
          hideChevron={!plan.showProjectChevron}
        />
      </div>
      {plan.showLocal ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          <span
            className="ds-workspace-context-status inline-flex h-7 shrink-0 items-center gap-1 px-1.5"
            title={t('contextBarLocalHint')}
            aria-label={t('contextBarLocalHint')}
          >
            <Laptop className="h-3 w-3 shrink-0" strokeWidth={1.7} aria-hidden />
            {plan.showLocalLabel ? <span>{t('contextBarLocal')}</span> : null}
          </span>
        </>
      ) : null}
      {showBranch ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          <div className="ds-workspace-context-branch min-w-0 shrink">
            <GitBranchPicker
              key={normalizedRoot}
              workspaceRoot={normalizedRoot}
              compact
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
