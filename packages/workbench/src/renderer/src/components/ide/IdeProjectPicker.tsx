import { useRef, useState, type ReactElement } from 'react'
import { Check, ChevronDown, FolderOpen, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { workspaceLabelFromPath } from '../../lib/workspace-label'

export type IdeProjectOption = {
  path: string
  name: string
}

type Props = {
  currentPath: string
  projectName: string
  options: ReadonlyArray<IdeProjectOption>
  onSelectProject: (workspacePath: string) => void
  onBrowseProject?: () => void
}

export function IdeProjectPicker({
  currentPath,
  projectName,
  options,
  onSelectProject,
  onBrowseProject
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const normalizedCurrent = currentPath.trim()

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [rootRef]
  })

  return (
    <div ref={rootRef} className="ds-ide-project-picker relative min-w-0 max-w-full">
      <button
        type="button"
        className="ds-ide-project-picker__trigger ds-no-drag"
        aria-label={t('ideSwitchProject')}
        title={t('ideSwitchProject')}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="ds-ide-project-picker__identity min-w-0">
          <span className="ds-ide-project-picker__name truncate" title={projectName}>
            {projectName}
          </span>
          {normalizedCurrent ? (
            <span className="ds-ide-project-picker__path truncate" title={normalizedCurrent}>
              {normalizedCurrent}
            </span>
          ) : (
            <span className="ds-ide-project-picker__path truncate">{t('ideWorkspaceNoRoot')}</span>
          )}
        </span>
        <ChevronDown
          className={`ds-ide-project-picker__chevron h-3.5 w-3.5 shrink-0 ${
            open ? 'ds-ide-project-picker__chevron--open' : ''
          }`}
          strokeWidth={1.85}
        />
      </button>

      {open ? (
        <div
          className="ds-ide-project-picker-menu"
          role="menu"
          aria-label={t('ideSwitchProject')}
        >
          <div className="ds-ide-project-picker-menu__title">{t('ideProjectPickerTitle')}</div>
          <div className="ds-ide-project-picker-menu__list">
            {options.length === 0 ? (
              <p className="ds-ide-project-picker-menu__empty">{t('ideProjectPickerEmpty')}</p>
            ) : (
              options.map((option) => {
                const active = option.path === normalizedCurrent
                return (
                  <button
                    key={option.path}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    title={option.path}
                    className={`ds-ide-project-picker-menu__row ${
                      active ? 'ds-ide-project-picker-menu__row--active' : ''
                    }`}
                    onClick={() => {
                      setOpen(false)
                      if (!active) onSelectProject(option.path)
                    }}
                  >
                    <FolderOpen className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.85} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-medium tracking-[-0.01em]">
                        {option.name || workspaceLabelFromPath(option.path)}
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-ds-faint">
                        {option.path}
                      </span>
                    </span>
                    <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center text-ds-ink">
                      {active ? <Check className="h-3.5 w-3.5" strokeWidth={2.1} /> : null}
                    </span>
                  </button>
                )
              })
            )}
          </div>
          {onBrowseProject ? (
            <div className="ds-ide-project-picker-menu__footer">
              <button
                type="button"
                role="menuitem"
                className="ds-ide-project-picker-menu__row"
                onClick={() => {
                  setOpen(false)
                  onBrowseProject()
                }}
              >
                <Plus className="h-3.5 w-3.5 shrink-0" strokeWidth={1.9} />
                <span className="truncate text-[12.5px]">{t('ideProjectPickerBrowse')}</span>
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
