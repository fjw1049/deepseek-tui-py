import { type ReactElement } from 'react'
import { Laptop } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { GitBranchPicker } from './GitBranchPicker'
import { ProjectContextPicker } from './ProjectContextPicker'

type Props = {
  workspaceRoot: string
}

/** Empty-stage tray tucked under the composer shell. */
export function WorkspaceContextBar({ workspaceRoot }: Props): ReactElement {
  const { t } = useTranslation('common')
  const normalizedRoot = normalizeWorkspaceRoot(workspaceRoot)
  const isTemporary = isChatsWorkspace(workspaceRoot) || !normalizedRoot
  const showBranch = Boolean(normalizedRoot) && !isTemporary

  return (
    <div
      className="ds-workspace-context-bar relative z-0 -mt-5 flex min-h-8 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden rounded-b-[1.2rem] rounded-t-none px-2.5 pb-1.5 pt-6 sm:min-h-7 sm:px-3.5"
      data-workspace-context-bar="true"
    >
      <ProjectContextPicker
        workspaceRoot={workspaceRoot}
        usePortal
        menuPlacement="above"
      />
      <span className="ds-workspace-context-sep" aria-hidden />
      <span
        className="ds-workspace-context-chip ds-workspace-context-chip--static inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 py-1"
        title={t('contextBarLocal')}
      >
        <Laptop className="h-3.5 w-3.5 shrink-0" strokeWidth={1.7} />
        <span>{t('contextBarLocal')}</span>
      </span>
      {showBranch ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          <div className="ds-workspace-context-branch min-w-0">
            <GitBranchPicker
              key={normalizedRoot}
              workspaceRoot={normalizedRoot}
              compact
              usePortal
              menuPlacement="above"
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
