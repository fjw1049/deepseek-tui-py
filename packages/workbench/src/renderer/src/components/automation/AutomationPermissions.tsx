import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { formatAutomationApiError } from '../../lib/automation-runtime-client'

export function AutomationPermissions({ automationId }: { automationId: string }): ReactElement {
  const { t } = useTranslation('common')
  const [allowed, setAllowed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const path = `/v1/automations/${encodeURIComponent(automationId)}/permissions`
  useEffect(() => {
    let active = true
    setLoaded(false)
    setError('')
    void Promise.resolve().then(() => window.dsGui.runtimeRequest(path, 'GET')).then((response) => {
      if (!active) return
      if (!response.ok) throw new Error(formatAutomationApiError(response.body, `HTTP ${response.status}`))
      setAllowed(JSON.parse(response.body).allow_browser === true)
      setLoaded(true)
    }).catch((err) => { if (active) setError(String(err instanceof Error ? err.message : err)) })
    return () => { active = false }
  }, [path])
  const toggle = async (): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      const response = await window.dsGui.runtimeRequest(path, 'PUT', JSON.stringify({ allow_browser: !allowed }))
      if (!response.ok) throw new Error(formatAutomationApiError(response.body, t('automationPermissionFailed')))
      setAllowed(JSON.parse(response.body).allow_browser === true)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  return <section className="grid gap-2 rounded-2xl border border-ds-border p-4">
    <label className="flex items-center gap-2 text-[13px] font-semibold">
      <input type="checkbox" checked={allowed} disabled={!loaded || busy} onChange={() => void toggle()} />
      {t('automationAllowBrowser')}
    </label>
    <p className="text-[12px] text-ds-muted">{t('automationBrowserScope')}</p>
    {error ? <p role="alert">{error}</p> : null}
  </section>
}
