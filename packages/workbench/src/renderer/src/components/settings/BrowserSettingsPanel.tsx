import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe, MessageSquare } from 'lucide-react'
import type { AppSettingsPatch, AppSettingsV1 } from '@shared/app-settings'
import { SettingsToggle } from './SettingsToggle'
import { SettingsSelect } from './SettingsSelect'
import { settingsToolbarButtonClass } from './SettingsActionToolbar'
import { BrowserCookieSync } from '../BrowserCookieSync'
import { browserRequest } from '../BrowserWorkspace'
import { useChatStore } from '../../store/chat-store'

type Grant = { thread_id: string; thread_title?: string; site: string }
type RuntimeSettings = { agent_enabled: boolean; grants: Grant[] }
const previewThread = 'workbench-preview'

function grantsByChat(grants: Grant[]): Array<[string, Grant[]]> {
  const groups = new Map<string, Grant[]>()
  for (const grant of grants) groups.set(grant.thread_id, [...(groups.get(grant.thread_id) ?? []), grant])
  return [...groups]
}

export function BrowserSettingsPanel({ form, onUpdate }: {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}): React.JSX.Element {
  const { t } = useTranslation('settings')
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [cookies, setCookies] = useState(false)
  const openSettings = useChatStore(s => s.openSettings)
  async function load(): Promise<void> {
    setError(false)
    try { setRuntime(await browserRequest<RuntimeSettings>(previewThread, '/settings')) }
    catch { setRuntime(null); setError(true) }
  }
  useEffect(() => { void load() }, [])
  async function change(body: unknown, suffix = '/settings'): Promise<void> {
    setBusy(true); setError(false)
    try { await browserRequest(previewThread, suffix, body); await load() }
    catch { setError(true) }
    finally { setBusy(false) }
  }
  async function chooseDirectory(): Promise<void> {
    setError(false)
    try {
      const result = await window.dsGui.pickWorkspaceDirectory(form.browserDownloadDirectory || undefined)
      if (!result.canceled && result.path) onUpdate({ browserDownloadDirectory: result.path })
    } catch { setError(true) }
  }
  function row(title: string, hint: ReactNode, control: ReactNode): React.JSX.Element {
    return <div className="ds-setting-row ds-density-row flex flex-col gap-3 px-3 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
      <div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{t(title)}</h3>
        <p className="mt-0.5 max-w-md break-words text-[13px] leading-relaxed text-ds-muted">{typeof hint === 'string' ? t(hint) : hint}</p></div>
      <div className="shrink-0 sm:ml-auto">{control}</div>
    </div>
  }
  function section(title: string, children: ReactNode, action?: ReactNode): React.JSX.Element {
    return <section className="ds-content-card rounded-2xl">
      <div className="flex items-center justify-between gap-4 border-b border-ds-border-muted px-5 py-3">
        <h2 className="text-base font-semibold">{t(title)}</h2>{action}
      </div>
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  }
  function linkTarget(key: 'browserLinkTarget' | 'browserLocalLinkTarget'): React.JSX.Element {
    return <SettingsSelect aria-label={t(key)} className="w-36" value={form[key] ?? 'external'} onChange={e => onUpdate({ [key]: e.target.value })}>
      <option value="external">{t('browserExternal')}</option><option value="internal">{t('browserInternal')}</option>
    </SettingsSelect>
  }
  const button = settingsToolbarButtonClass()
  return <div className="space-y-6 text-ds-ink">
    {error && <div role="alert" className="text-sm text-ds-danger">{t('browserSettingsError')} <button className={button} onClick={() => void load()}>{t('browserRetry')}</button></div>}
    {section('browserControl', <>
      {row('browserAgentEnabled', runtime ? 'browserAgentEnabledHint' : 'browserLoading', <SettingsToggle label={t('browserAgentEnabled')} checked={runtime?.agent_enabled === true} disabled={!runtime || busy} onChange={value => void change({ agent_enabled: value })} />)}
      {row('browserChromeConnection', 'browserChromeConnectionHint', <button className={button} onClick={() => openSettings('computer-control')}>{t('browserManage')}</button>)}
    </>)}
    {section('browserLinks', <>
      {row('browserLinkTarget', 'browserLinkTargetHint', linkTarget('browserLinkTarget'))}
      {row('browserLocalLinkTarget', 'browserLocalLinkTargetHint', linkTarget('browserLocalLinkTarget'))}
    </>)}
    {section('browserData', <>
      {row('browserSignIn', 'browserSignInHint', <button className={button} disabled={!runtime} onClick={() => setCookies(true)}>{t('browserManage')}</button>)}
    </>)}
    {section('browserDownloads', <>
      {row('browserDownloadDirectory', form.browserDownloadDirectory ? <span>{form.browserDownloadDirectory}</span> : 'browserSystemDownloads', <div className="flex gap-2"><button className={button} onClick={() => void chooseDirectory()}>{t('browserChange')}</button>
        {form.browserDownloadDirectory && <button className={button} onClick={() => onUpdate({ browserDownloadDirectory: '' })}>{t('browserReset')}</button>}</div>)}
      {row('browserAskDownloadLocation', 'browserAskDownloadLocationHint', <SettingsToggle label={t('browserAskDownloadLocation')} checked={form.browserAskDownloadLocation !== false} onChange={value => onUpdate({ browserAskDownloadLocation: value })} />)}
    </>)}
    {section('browserPermissions', <>
      <p className="px-5 py-4 text-[13px] leading-5 text-ds-muted">{t('browserPermissionsHint')}</p>
      {!runtime && !error && <p className="px-5 py-4 text-sm text-ds-muted">{t('browserLoading')}</p>}
      {runtime?.grants.length === 0 && <p className="px-5 py-4 text-sm text-ds-muted">{t('browserNoGrants')}</p>}
      {grantsByChat(runtime?.grants ?? []).map(([threadId, grants]) => <div key={threadId} className="px-3 py-3">
        <div className="flex items-center gap-2 px-2 pb-1 text-xs text-ds-muted">
          <MessageSquare size={13} className="shrink-0" aria-hidden="true" />
          <span className="min-w-0 truncate" title={grants[0].thread_title}>{grants[0].thread_title || t('browserUntitledChat')}</span>
          <span className="shrink-0">· {t('browserGrantCount', { count: grants.length })}</span>
        </div>
        {grants.map(grant => <div key={grant.site} className="flex items-center justify-between gap-4 rounded-lg px-2 py-1.5 hover:bg-ds-hover">
          <div className="flex min-w-0 items-center gap-2.5">
            <Globe size={15} className="shrink-0 text-ds-faint" aria-hidden="true" />
            <span className="truncate text-sm" title={grant.site}>{grant.site.replace(/^https:\/\//, '')}</span>
          </div>
          <button className={button} disabled={busy} onClick={() => void change({ thread_id: grant.thread_id, site: grant.site }, '/settings/revoke')}>{t('browserRevoke')}</button>
        </div>)}
      </div>)}
    </>, <button className={button} disabled={busy} onClick={() => void load()}>{t('browserRefresh')}</button>)}
    {cookies && <BrowserCookieSync threadId={previewThread} manage settingsDialog onOpen={() => setCookies(true)} onClose={() => setCookies(false)} />}
  </div>
}
