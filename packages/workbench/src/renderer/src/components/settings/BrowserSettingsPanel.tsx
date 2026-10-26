import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
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
  function section(title: string, children: ReactNode): React.JSX.Element {
    return <section className="ds-content-card rounded-2xl">
      <h2 className="border-b border-ds-border-muted px-5 py-3 text-base font-semibold">{t(title)}</h2>
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  }
  function linkTarget(key: 'browserLinkTarget' | 'browserLocalLinkTarget'): React.JSX.Element {
    return <SettingsSelect aria-label={t(key)} value={form[key] ?? 'external'} onChange={e => onUpdate({ [key]: e.target.value })}>
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
      <p className="px-5 py-4 text-[13px] leading-5 text-ds-muted">{t('browserDownloadScope')}</p>
    </>)}
    {section('browserPermissions', <>
      <p className="px-5 py-4 text-[13px] leading-5 text-ds-muted">{t('browserPermissionsHint')}</p>
      {runtime?.grants.length === 0 && <p className="px-5 py-4 text-sm text-ds-muted">{t('browserNoGrants')}</p>}
      {runtime?.grants.map(grant => <div key={`${grant.thread_id}:${grant.site}`} className="flex items-center justify-between gap-4 px-5 py-4">
        <div className="min-w-0"><p className="break-all text-sm">{grant.site}</p><p className="break-all text-xs text-ds-muted">{t('browserGrantConversation', { id: grant.thread_title || t('browserUntitledChat') })}</p></div>
        <button className={button} disabled={busy} onClick={() => void change({ thread_id: grant.thread_id, site: grant.site }, '/settings/revoke')}>{t('browserRevoke')}</button>
      </div>)}
      <div className="px-5 py-3"><button className={button} disabled={busy} onClick={() => void load()}>{t('browserRefresh')}</button></div>
    </>)}
    {cookies && <BrowserCookieSync threadId={previewThread} manage settingsDialog onOpen={() => setCookies(true)} onClose={() => setCookies(false)} />}
  </div>
}
