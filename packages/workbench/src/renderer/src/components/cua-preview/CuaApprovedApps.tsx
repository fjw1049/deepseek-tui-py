import { useEffect, useRef, useState } from 'react'
import { AppWindow, LoaderCircle, Plus, Trash2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type ApprovedApp = { name: string; bundleId: string; installed?: boolean; icon?: string | null; blocked?: boolean }

async function cuaAppsRequest(path: string, body?: unknown): Promise<ApprovedApp[]> {
  const response = body === undefined
    ? await window.dsGui.runtimeRequest(path, 'GET')
    : await window.dsGui.runtimeRequest(path, 'POST', JSON.stringify(body))
  if (!response.ok) throw new Error('Apps unavailable')
  const value = JSON.parse(response.body) as { apps?: ApprovedApp[] }
  if (!Array.isArray(value?.apps)) throw new Error('Invalid apps')
  return value.apps.filter(app => typeof app?.bundleId === 'string')
}

function AppIcon({ app }: { app: ApprovedApp }): React.JSX.Element {
  const [failed, setFailed] = useState(false)
  return <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl">
    {!failed && app.icon?.startsWith('data:image/png;base64,')
      ? <img src={app.icon} alt="" className="h-10 w-10 object-contain" onError={() => setFailed(true)} />
      : <AppWindow size={28} className="text-ds-muted" aria-hidden="true" />}
  </span>
}

/** Grants stay in the runtime's store; every mutation uses its owner authentication. */
export function CuaApprovedApps(): React.JSX.Element {
  const { t } = useTranslation('common')
  const [apps, setApps] = useState<ApprovedApp[] | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const mutation = useRef(false)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  const [picker, setPicker] = useState(false)
  const [available, setAvailable] = useState<ApprovedApp[] | null>(null)
  const [pickerError, setPickerError] = useState(false)
  const [query, setQuery] = useState('')
  useEffect(() => {
    setApps(null)
    setError(false)
    let live = true
    cuaAppsRequest('/v1/cua/apps').then(list => { if (live) setApps(list) }, () => { if (live) setError(true) })
    return () => { live = false }
  }, [revision])
  useEffect(() => {
    if (!picker) return
    let live = true
    setAvailable(null)
    setPickerError(false)
    cuaAppsRequest('/v1/cua/apps/available').then(
      list => { if (live) setAvailable(list) }, () => { if (live) setPickerError(true) }
    )
    return () => { live = false }
  }, [picker])
  const update = async (bundleId: string, action: 'allow' | 'revoke'): Promise<void> => {
    if (mutation.current) return
    mutation.current = true
    setPending(bundleId)
    setError(false)
    try { setApps(await cuaAppsRequest(`/v1/cua/apps/${action}`, { app: bundleId })) }
    catch {
      try {
        const actual = await cuaAppsRequest('/v1/cua/apps')
        setApps(actual)
        setError(actual.some(app => app.bundleId === bundleId) !== (action === 'allow'))
      } catch { setError(true) }
    }
    finally { mutation.current = false; setPending(null) }
  }
  const busy = pending !== null || (apps === null && !error)
  const choices = available?.filter(app => !apps?.some(granted => granted.bundleId === app.bundleId)
    && `${app.name} ${app.bundleId}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  return <section className="overflow-hidden rounded-2xl border border-ds-border bg-ds-card">
    <div className="flex min-h-16 items-center justify-between gap-4 border-b border-ds-border-muted px-5 py-3">
      <h3 className="text-[15px] font-medium leading-6 text-ds-ink">{t('computerUseApprovedApps')}</h3>
        <button type="button" disabled={busy} onClick={() => { setPicker(!picker); setQuery('') }}
          className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-ds-border px-3 text-[13px] font-medium leading-none text-ds-ink hover:bg-ds-hover disabled:opacity-40"
          aria-expanded={picker}>
          {picker ? <X size={16} aria-hidden="true" /> : <Plus size={16} aria-hidden="true" />}
          {t(picker ? 'computerUseClosePicker' : 'computerUseAddApp')}
        </button>
    </div>
    {apps === null && !error ? <p role="status" className="px-5 py-4 text-sm text-ds-muted">{t('computerUseChecking')}</p> : null}
    {apps?.length === 0 ? <p className="px-5 py-4 text-sm text-ds-muted">{t('computerUseApprovedAppsEmpty')}</p> : null}
    {apps?.length ? <ul className="max-h-[323px] divide-y divide-ds-border-muted overflow-y-auto px-5">
      {apps.map(app => <li key={app.bundleId} className="flex min-h-[80px] items-center gap-5 py-4">
        <AppIcon app={app} />
        <span className="min-w-0 flex-1 truncate text-[16px] font-medium text-ds-ink" title={app.name || app.bundleId}>{app.name || app.bundleId}</span>
        <button type="button" disabled={pending !== null} onClick={() => void update(app.bundleId, 'revoke')}
          aria-label={`${t('computerUseRevoke')} ${app.name || app.bundleId}`} title={t('computerUseRevoke')}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-500/10 text-red-500 hover:bg-red-500/20 active:scale-95 disabled:opacity-40">
          {pending === app.bundleId ? <LoaderCircle size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={16} aria-hidden="true" />}
        </button>
      </li>)}
    </ul> : null}
    {picker && <div className="m-5 rounded-xl border border-ds-border p-4">
      <input type="search" autoFocus aria-label={t('computerUseSearchApps')} placeholder={t('computerUseSearchApps')}
        value={query} onChange={event => setQuery(event.target.value)}
        className="w-full rounded-xl border border-ds-border bg-ds-subtle px-3 py-2 text-sm text-ds-ink outline-none focus:ring-2 focus:ring-ds-muted" />
      <p className="mt-2 text-xs leading-5 text-ds-muted">{t('computerUseAllowHint')}</p>
      {!available && !pickerError && <p role="status" className="px-5 py-4 text-sm text-ds-muted">{t('computerUseChecking')}</p>}
      {pickerError && <p role="alert" className="py-4 text-sm text-ds-danger">{t('computerUseAppsError')}</p>}
      {choices?.length === 0 && <p className="px-5 py-4 text-sm text-ds-muted">{t('computerUseNoApps')}</p>}
      <ul className="mt-2 max-h-72 divide-y divide-ds-border-muted overflow-y-auto">
        {choices?.map(app => <li key={app.bundleId} className="flex items-center gap-3 py-3">
          <AppIcon app={app} />
          <span className="min-w-0 flex-1 truncate text-sm text-ds-ink">{app.name}</span>
          <button type="button" disabled={busy || app.blocked} onClick={() => void update(app.bundleId, 'allow')}
            className="shrink-0 rounded-lg border border-ds-border px-3 py-2 text-xs text-ds-ink hover:bg-ds-hover disabled:opacity-40">
            {t(app.blocked ? 'computerUseAppBlocked' : pending === app.bundleId ? 'computerUseUpdating' : 'computerUseAlwaysAllow')}
          </button>
        </li>)}
      </ul>
    </div>}
    {pending && <p role="status" className="mt-3 text-xs text-ds-muted">{t('computerUseOwnerAuth')}</p>}
    {error ? <div className="mt-3 flex items-center gap-3 px-5">
      <p role="alert" className="text-sm text-ds-danger">{t('computerUseAppsError')}</p>
      <button type="button" disabled={busy} title={t('computerUseRefresh')}
        onClick={() => setRevision(value => value + 1)} className="shrink-0 text-sm text-ds-muted underline disabled:opacity-40">
        {t('computerUseRefresh')}
      </button>
    </div> : null}
    <details className="border-t border-ds-border-muted px-5 py-3 text-xs leading-5 text-ds-muted">
      <summary className="w-fit cursor-pointer hover:text-ds-ink">{t('computerUsePermissionDetails')}</summary>
      <p className="mt-2">{t('computerUseApprovedAppsHint')}</p>
      <p className="mt-1">{t('computerUseRevokeHint')}</p>
    </details>
  </section>
}
