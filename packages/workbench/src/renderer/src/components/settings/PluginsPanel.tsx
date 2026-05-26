import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { SKILL_MARKETPLACE_URL } from '@shared/marketplace-links'
import { openExternalUrl } from '../../lib/open-marketplace'
import { SettingsActionToolbar, settingsToolbarButtonClass } from './SettingsActionToolbar'

export type InstalledPluginSummary = {
  id: string
  name: string
  path: string
}

type Props = {
  skillsDir: string
  plugins: InstalledPluginSummary[]
  loading: boolean
  onReload: () => void | Promise<void>
  onOpenSkillsDir: () => void | Promise<void>
}

export function PluginsPanel({
  skillsDir,
  plugins,
  loading,
  onReload,
  onOpenSkillsDir
}: Props): ReactElement {
  const { t } = useTranslation('settings')

  return (
    <div className="flex w-full flex-col gap-4">
      <p className="text-[13px] leading-6 text-ds-muted">{t('pluginsListDesc')}</p>
      <code className="block break-all rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[11px] text-ds-faint">
        {skillsDir}
      </code>

      {loading ? (
        <div className="flex items-center gap-2 py-6 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('loading')}
        </div>
      ) : plugins.length === 0 ? (
        <div className="rounded-xl border border-dashed border-ds-border bg-ds-main/40 px-4 py-6 text-center text-[13px] leading-6 text-ds-muted">
          {t('pluginsListEmpty')}
        </div>
      ) : (
        <ul className="divide-y divide-ds-border-muted overflow-hidden rounded-xl border border-ds-border bg-ds-card">
          {plugins.map((plugin) => (
            <li key={plugin.id} className="px-4 py-3">
              <div className="text-[14px] font-semibold text-ds-ink">{plugin.name}</div>
              <div className="mt-0.5 truncate font-mono text-[11px] text-ds-faint">{plugin.path}</div>
            </li>
          ))}
        </ul>
      )}

      <p className="text-[12px] leading-5 text-ds-faint">{t('pluginsRuntimeHint')}</p>

      <SettingsActionToolbar>
        <button
          type="button"
          onClick={() => void onReload()}
          disabled={loading}
          className={settingsToolbarButtonClass(loading)}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} strokeWidth={1.75} />
          {t('pluginsRefresh')}
        </button>
        <button
          type="button"
          onClick={() => void onOpenSkillsDir()}
          className={settingsToolbarButtonClass()}
        >
          <FolderOpen className="h-4 w-4" />
          {t('pluginsOpenConfigFolder')}
        </button>
        <button
          type="button"
          onClick={() => openExternalUrl(SKILL_MARKETPLACE_URL)}
          className={settingsToolbarButtonClass()}
        >
          <ExternalLink className="h-4 w-4" strokeWidth={1.75} />
          {t('skillsOpenMarketplace')}
        </button>
      </SettingsActionToolbar>
    </div>
  )
}
