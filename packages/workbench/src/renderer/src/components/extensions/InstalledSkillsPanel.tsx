import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, FolderOpen, Loader2, Trash2 } from 'lucide-react'

export type InstalledSkill = {
  id: string
  name: string
  path: string
  description: string
  builtin: boolean
}

type SkillTab = 'installed' | 'marketplace'

type Props = {
  skills: InstalledSkill[]
  loading: boolean
  busyId: string | null
  onPreview: (skill: InstalledSkill) => void
  onOpen: (skill: InstalledSkill) => void
  onDelete: (skill: InstalledSkill) => void
  /** Content rendered when the ModelScope 市场 tab is active. */
  marketplaceSlot?: ReactElement
  /** Optional content pinned to the right of the tab row (e.g. a hint). */
  headerRight?: ReactElement
}

/**
 * Installed-skills list with 已安装 / ModelScope 市场 segmented tabs. The 已安装
 * tab shows every local skill; built-in skills carry the bundled
 * `.system-installed-version` marker and cannot be deleted (no delete action),
 * while user skills reveal an open/delete action row on hover. The marketplace
 * tab renders `marketplaceSlot` (the ModelScope browser).
 */
export function InstalledSkillsPanel({
  skills,
  loading,
  busyId,
  onPreview,
  onOpen,
  onDelete,
  marketplaceSlot,
  headerRight
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<SkillTab>('installed')

  return (
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between gap-4 border-b border-ds-border-muted px-5 pt-4">
        <div className="flex items-center gap-5">
          <SkillTabButton active={tab === 'installed'} count={skills.length} onClick={() => setTab('installed')}>
            {t('skillTabInstalled')}
          </SkillTabButton>
          <SkillTabButton active={tab === 'marketplace'} onClick={() => setTab('marketplace')}>
            {t('marketplaceTitle')}
          </SkillTabButton>
        </div>
        {headerRight ? <div className="pb-3 pl-3">{headerRight}</div> : null}
      </div>

      {tab === 'marketplace' ? null : loading ? (
        <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('skillsLoading')}
        </div>
      ) : skills.length === 0 ? (
        <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
          {t('skillsInstalledEmpty')}
        </div>
      ) : (
        <ul className="divide-y divide-ds-border-muted/70">
          {skills.map((skill) => (
            <SkillRow
              key={skill.id}
              skill={skill}
              busy={busyId === skill.id}
              onPreview={() => onPreview(skill)}
              onOpen={() => onOpen(skill)}
              onDelete={() => onDelete(skill)}
            />
          ))}
        </ul>
      )}
      {/* MarketplaceBrowser stays mounted across tabs so the parent's top
          "重新加载" refresh signal reaches it even while the market tab is
          hidden — otherwise the signal would fire into an unmounted component
          and the catalog would never re-fetch. */}
      <div className={tab === 'marketplace' ? '' : 'hidden'}>
        {marketplaceSlot ?? null}
      </div>
    </div>
  )
}

function SkillTabButton({
  active,
  count,
  onClick,
  children
}: {
  active: boolean
  count?: number
  onClick: () => void
  children: string
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative -mb-px flex items-center gap-1.5 border-b-2 pb-3 text-[15px] font-semibold transition ${
        active ? 'border-ds-ink text-ds-ink' : 'border-transparent text-ds-muted hover:text-ds-ink'
      }`}
    >
      {children}
      {count !== undefined ? (
        <span
          className={`inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold ${
            active ? 'bg-ds-ink/10 text-ds-ink' : 'bg-ds-subtle text-ds-faint'
          }`}
        >
          {count}
        </span>
      ) : null}
    </button>
  )
}

function SkillRow({
  skill,
  busy,
  onPreview,
  onOpen,
  onDelete
}: {
  skill: InstalledSkill
  busy: boolean
  onPreview: () => void
  onOpen: () => void
  onDelete: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const stop = (handler: () => void) => (event: ReactMouseEvent): void => {
    event.stopPropagation()
    handler()
  }
  return (
    <li
      role="button"
      tabIndex={0}
      onClick={onPreview}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onPreview()
        }
      }}
      title={t('skillPreviewHint')}
      className="group flex cursor-pointer items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 focus:bg-ds-subtle/50 focus:outline-none"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        <FileText className="h-4.5 w-4.5" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-semibold text-ds-ink">{skill.name}</div>
        <p className="mt-0.5 line-clamp-1 text-[13px] leading-5 text-ds-muted" title={skill.description || skill.path}>
          {skill.description || skill.path}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 opacity-0 transition group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          onClick={stop(onOpen)}
          title={t('skillOpen')}
          aria-label={t('skillOpen')}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
        >
          <FolderOpen className="h-4 w-4" strokeWidth={1.75} />
        </button>
        {skill.builtin ? null : (
          <button
            type="button"
            onClick={stop(onDelete)}
            disabled={busy}
            title={t('skillDelete')}
            aria-label={t('skillDelete')}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/30"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Trash2 className="h-4 w-4" strokeWidth={1.75} />}
          </button>
        )}
      </div>
    </li>
  )
}
