import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cacheSettingsSnapshot } from '../../lib/settings-snapshot'

export type CuaSetupState = {
  target: string | null
  chatgpt: boolean
  lcu: { installed: boolean; version: string | null; pinned: string }
  chromeConnector: 'installed' | 'missing' | 'unknown'
  busy: boolean
  links: { chatgpt: string; guide: string }
}
type ChromeCheck = { connected: boolean; reason: string | null }
type Action = 'lcu' | 'connector' | 'verify' | 'enable'

async function request<T>(path: string, method: 'GET' | 'POST'): Promise<T> {
  const response = await window.dsGui.runtimeRequest(path, method)
  const body = response.body ? JSON.parse(response.body) : {}
  // Runtime errors arrive as {detail: {message, error}}.
  if (!response.ok) throw new Error(typeof body?.detail?.message === 'string' ? body.detail.message : '')
  return body as T
}

function isSetupState(value: unknown): value is CuaSetupState {
  const v = value as CuaSetupState
  return Boolean(v && typeof v.chatgpt === 'boolean' && v.lcu && typeof v.lcu.installed === 'boolean'
    && v.links && typeof v.links.guide === 'string')
}

const buttonClass = 'min-w-24 shrink-0 rounded-lg border border-ds-border px-3 py-1.5 text-sm text-ds-ink hover:bg-ds-hover disabled:opacity-40'

function Step({ done, title, detail, children }: { done: boolean | null; title: string; detail?: string; children?: React.ReactNode }): React.JSX.Element {
  return <li className="flex items-center gap-3 py-3">
    <span aria-hidden className={`inline-flex size-5 shrink-0 items-center justify-center rounded-full text-xs ${done ? 'bg-ds-subtle text-ds-ink' : 'border border-ds-border text-ds-muted'}`}>{done ? '✓' : ''}</span>
    <div className="min-w-0 flex-1">
      <p className="text-sm text-ds-ink">{title}</p>
      {detail ? <p className="mt-0.5 text-xs text-ds-muted">{detail}</p> : null}
    </div>
    {children ? <div className="flex w-32 shrink-0 flex-col items-stretch gap-2">{children}</div> : null}
  </li>
}

/** Each component computer use needs, its state, and a one-click action where one exists. */
export function CuaSetupChecklist({ onOpenPermissions, onChanged }: {
  onOpenPermissions?: () => void
  onChanged: () => void
}): React.JSX.Element {
  const { t } = useTranslation('common')
  const [setup, setSetup] = useState<CuaSetupState | null>(null)
  const [running, setRunning] = useState<Action | null>(null)
  // A runtime message, or a translation key for the host's own text.
  const [error, setError] = useState<{ text?: string; key?: string } | null>(null)
  const [chrome, setChrome] = useState<ChromeCheck | null>(null)
  const [chromeEnabled, setChromeEnabled] = useState(false)
  const mac = window.dsGui.platform === 'darwin'

  const load = useCallback(async () => {
    try {
      const value = await request<unknown>('/v1/cua/setup', 'GET')
      if (!isSetupState(value)) throw new Error('')
      setSetup(value)
    } catch { setError({ key: 'cuaSetupUnavailable' }) }
  }, [])
  useEffect(() => { void load() }, [load])

  const run = async (action: Action, work: () => Promise<void>): Promise<void> => {
    if (running) return
    setRunning(action)
    setError(null)
    try {
      await work()
    } catch (cause) {
      setError(cause instanceof Error && cause.message ? { text: cause.message } : { key: 'cuaSetupFailed' })
    } finally {
      setRunning(null)
      await load()
      onChanged()
    }
  }
  const installLcu = (): Promise<void> => run('lcu', async () => { await request('/v1/cua/setup/lcu', 'POST') })
  const installConnector = (): Promise<void> => run('connector', async () => {
    await request('/v1/cua/setup/chrome', 'POST')
    setChrome(null)
  })
  const verifyChrome = (): Promise<void> => run('verify', async () => {
    setChrome(await request<ChromeCheck>('/v1/cua/setup/chrome/verify', 'POST'))
  })
  const enableChrome = (): Promise<void> => run('enable', async () => {
    cacheSettingsSnapshot(await window.dsGui.setSettings({ cuaChrome: true }))
    setChromeEnabled(true)
  })
  const open = (url: string): void => { void window.dsGui.openExternal(url) }
  const openInChrome = (page: 'store' | 'extension'): void => { void window.dsGui.openChromeSetupPage(page) }

  const errorText = error ? error.text ?? t(error.key ?? 'cuaSetupFailed') : ''
  if (!setup) {
    return <div className="mt-4"><p role={error ? 'alert' : 'status'} className={`mt-4 text-sm ${error ? 'text-ds-danger' : 'text-ds-muted'}`}>{errorText || t('cuaSetupChecking')}</p>{error && <button type="button" className={`${buttonClass} mt-3`} onClick={() => { setError(null); void load() }}>{t('computerUseRefresh')}</button>}</div>
  }
  const lcuReady = setup.lcu.installed
  const oneClick = Boolean(setup.target) && setup.chatgpt
  return <section aria-label={t('cuaSetupTitle')} className="mt-5 rounded-2xl border border-ds-border bg-ds-card px-5 py-3">
    <h3 className="pb-2 text-[15px] font-medium text-ds-ink">{t('cuaSetupTitle')}</h3>
    <ol className="divide-y divide-ds-border">
      {mac ? <Step done={setup.chatgpt} title={t('cuaSetupChatgpt')}
        detail={t(setup.chatgpt ? 'cuaSetupChatgptReady' : 'cuaSetupChatgptMissing')}>
        {!setup.chatgpt ? <button type="button" className={buttonClass} onClick={() => open(setup.links.chatgpt)}>{t('cuaSetupDownload')}</button> : null}
      </Step> : null}
      <Step done={lcuReady} title={t('cuaSetupLcu')}
        detail={lcuReady ? t('cuaSetupLcuReady', { version: setup.lcu.version }) : t(oneClick ? 'cuaSetupLcuMissing' : 'cuaSetupLcuManual', { version: setup.lcu.pinned })}>
        {!lcuReady && oneClick ? <button type="button" className={buttonClass} disabled={Boolean(running) || setup.busy} onClick={() => void installLcu()}>{t(running === 'lcu' || setup.busy ? 'cuaSetupInstalling' : 'cuaSetupInstall')}</button> : null}
        {!lcuReady && !oneClick ? <button type="button" className={buttonClass} onClick={() => open(setup.links.guide)}>{t('cuaSetupGuide')}</button> : null}
      </Step>
      {mac && onOpenPermissions ? <Step done={null} title={t('cuaSetupPermissions')} detail={t('cuaSetupPermissionsDetail')}>
        <button type="button" className={buttonClass} disabled={!lcuReady} onClick={onOpenPermissions}>{t('cuaSetupCheck')}</button>
      </Step> : null}
    </ol>
    {mac ? <>
      <h3 className="border-t border-ds-border pt-4 text-[15px] font-medium text-ds-ink">{t('cuaSetupChromeTitle')}</h3>
      <p className="text-xs text-ds-muted">{t('cuaSetupChromeIntro')}</p>
      <ol className="divide-y divide-ds-border">
        <Step done={setup.chromeConnector === 'installed'} title={t('cuaSetupChromeConnector')} detail={t('cuaSetupChromeConnectorDetail')}>
          {setup.chromeConnector !== 'installed' ? <button type="button" className={buttonClass} disabled={!lcuReady || Boolean(running)} onClick={() => void installConnector()}>{t(running === 'connector' ? 'cuaSetupConnecting' : 'cuaSetupConnect')}</button> : null}
        </Step>
        <Step done={chrome?.connected ?? null} title={t('cuaSetupChromeExtension')}
          detail={t(!chrome ? 'cuaSetupChromeExtensionDetail' : chrome.connected ? 'cuaSetupChromeConnected'
            : chrome.reason === 'extension' ? 'cuaSetupChromeNoExtension' : 'cuaSetupChromeNoRuntime')}>
          {chrome && !chrome.connected && chrome.reason === 'extension' ? <>
            <button type="button" className={buttonClass} onClick={() => openInChrome('store')}>{t('cuaSetupOpenStore')}</button>
            <button type="button" className={buttonClass} onClick={() => openInChrome('extension')}>{t('cuaSetupOpenExtension')}</button>
          </> : null}
          {chrome?.connected ? <button type="button" className={buttonClass} disabled={chromeEnabled || Boolean(running)} onClick={() => void enableChrome()}>{t(chromeEnabled ? 'cuaSetupChromeEnabled' : 'cuaSetupEnableChrome')}</button>
            : <button type="button" className={buttonClass} disabled={!lcuReady || setup.chromeConnector !== 'installed' || Boolean(running)} onClick={() => void verifyChrome()}>{t(running === 'verify' ? 'cuaSetupVerifying' : 'cuaSetupVerify')}</button>}
        </Step>
      </ol>
    </> : null}
    {error ? <p role="alert" className="pb-2 text-sm text-ds-danger">{errorText}</p> : null}
  </section>
}
