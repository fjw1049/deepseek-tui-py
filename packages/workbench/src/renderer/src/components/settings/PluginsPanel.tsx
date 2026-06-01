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
  showIntro?: boolean
  onReload: () => void | Promise<void>
  onOpenSkillsDir: () => void | Promise<void>
}

export function PluginsPanelHeader(): ReactElement {
  const { t } = useTranslation('settings')
  return (
    <>
      <p className="mt-1 max-w-3xl text-[13px] leading-6 text-ds-muted">{t('pluginsInstalledDesc')}</p>
      <p className="mt-2 max-w-3xl text-[13px] leading-6 text-ds-muted">{t('pluginsListDesc')}</p>
    </>
  )
}

export function PluginsPanel({
  skillsDir,
  plugins,
  loading,
  showIntro = true,
  onReload,
  onOpenSkillsDir
}: Props): ReactElement {
  const { t } = useTranslation('settings')

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      {showIntro ? (
        <>
          <p className="max-w-3xl text-[13px] leading-6 text-ds-muted">{t('pluginsListDesc')}</p>
          <code className="block w-full break-all rounded-xl bg-ds-main/70 px-3 py-2 font-mono text-[12px] text-ds-faint">
            {skillsDir}
          </code>
        </>
      ) : (
        <code className="block w-full break-all rounded-xl bg-ds-main/70 px-3 py-2 font-mono text-[12px] text-ds-faint">
          {skillsDir}
        </code>
      )}

      {loading ? (
        <div className="flex w-full items-center gap-2 py-6 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('loading')}
        </div>
      ) : plugins.length === 0 ? (
        <div className="w-full rounded-xl border border-dashed border-ds-border bg-ds-main/40 px-4 py-8 text-center text-[13px] leading-6 text-ds-muted">
          {t('pluginsListEmpty')}
        </div>
      ) : (
        <ul className="w-full divide-y divide-ds-border-muted overflow-hidden rounded-xl border border-ds-border bg-ds-card">
          {plugins.map((plugin) => (
            <li key={plugin.id} className="px-4 py-3">
              <div className="text-[14px] font-semibold text-ds-ink">{plugin.name}</div>
              <div className="mt-0.5 truncate font-mono text-[11px] text-ds-faint" title={plugin.path}>
                {plugin.path}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="flex w-full flex-col gap-3 border-t border-ds-border-muted pt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <p className="min-w-0 flex-1 text-[12px] leading-5 text-ds-faint">{t('pluginsRuntimeHint')}</p>
        <SettingsActionToolbar className="shrink-0 sm:justify-end">
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
    </div>
  )
}
