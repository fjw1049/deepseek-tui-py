import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppSettingsPatch, AppSettingsV1 } from '@shared/app-settings'
import { readTomlBool } from '@shared/toml-section'

type InheritedCua = { enabled: boolean; chrome: boolean; autoAllowApps: boolean }

/** The runtime reads ``[cua]`` from the user config only; an absent switch is off. */
async function readInheritedCua(): Promise<InheritedCua> {
  const { content } = await window.dsGui.getDeepseekConfigFile()
  return {
    enabled: readTomlBool(content ?? '', 'enabled', { section: 'cua' }) ?? false,
    chrome: readTomlBool(content ?? '', 'chrome', { section: 'cua' }) ?? false,
    autoAllowApps: readTomlBool(content ?? '', 'auto_allow_apps', { section: 'cua' }) ?? false
  }
}

type PrivacyEntry = { id: 'accessibility' | 'screen'; name: string }

async function readPrivacyEntries(): Promise<PrivacyEntry[]> {
  const response = await window.dsGui.runtimeRequest('/v1/cua/permissions', 'GET')
  if (!response.ok) throw new Error('Permissions unavailable')
  const value = JSON.parse(response.body) as { permissions?: PrivacyEntry[] }
  if (!Array.isArray(value?.permissions)) throw new Error('Invalid permissions')
  return value.permissions
}

/** macOS grants belong to the runtime's own signed apps; name them and open their panes. */
function SystemPermissions(): React.JSX.Element | null {
  const { t } = useTranslation('settings')
  const [entries, setEntries] = useState<PrivacyEntry[] | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    readPrivacyEntries().then(list => { if (live) setEntries(list) }, () => { if (live) setFailed(true) })
    return () => { live = false }
  }, [])
  const open = (id: PrivacyEntry['id']): void => {
    window.dsGui.runtimeRequest('/v1/cua/permissions/open', 'POST', JSON.stringify({ id }))
      .then(response => { if (!response.ok) setFailed(true) }, () => setFailed(true))
  }
  if (failed) return <p className="ds-llm-card__meta">{t('cuaPermissionsUnavailable')}</p>
  if (!entries?.length) return null
  return <>
    {entries.map(entry => <div className="ds-llm-card" key={entry.id}>
      <span>{t(entry.id === 'accessibility' ? 'cuaPermissionAccessibility' : 'cuaPermissionScreen',
        { name: entry.name })}</span>
      <button type="button" className="ds-llm-sheet__btn" onClick={() => open(entry.id)}>
        {t('cuaPermissionOpen')}
      </button>
    </div>)}
    <p className="ds-llm-card__meta">{t('cuaPermissionsHint')}</p>
  </>
}

export function CuaSettingsPanel({ form, onUpdate }: {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}): React.JSX.Element {
  const { t } = useTranslation('settings')
  // Matches the runtime adapter: LCU computer use has no Windows support.
  const supported = window.dsGui?.platform === 'darwin' || window.dsGui?.platform === 'linux'
  // undefined while loading, null when the config file could not be read.
  const [inherited, setInherited] = useState<InheritedCua | null | undefined>(undefined)
  useEffect(() => {
    if (!supported) return
    let cancelled = false
    readInheritedCua().then(
      value => { if (!cancelled) setInherited(value) },
      () => { if (!cancelled) setInherited(null) }
    )
    return () => { cancelled = true }
  }, [supported])

  if (!supported) {
    return <div className="ds-llm-panel__section">
      <h3 className="ds-llm-panel__section-title">{t('cuaTitle')}</h3>
      <p className="ds-llm-card__meta">{t('cuaUnsupported')}</p>
    </div>
  }
  const inheritLabel = (key: keyof InheritedCua): string => inherited === null
    ? t('cuaInheritedUnknown')
    : t('cuaInherited', { state: inherited === undefined ? '…' : t(inherited[key] ? 'cuaOn' : 'cuaOff') })
  const enabled = form.cuaEnabled ?? inherited?.enabled
  return <div className="ds-llm-panel__section">
    <h3 className="ds-llm-panel__section-title">{t('cuaTitle')}</h3>
    <p className="ds-llm-card__meta">{t('cuaDescription')}</p>
    <label className="ds-llm-card">
      <span>{t('cuaEnable')}</span>
      <select aria-label={t('cuaEnable')}
        value={form.cuaEnabled === undefined ? 'inherit' : String(form.cuaEnabled)}
        onChange={event => onUpdate({ cuaEnabled: event.target.value === 'true' })}>
        <option value="inherit" disabled>{inheritLabel('enabled')}</option>
        <option value="false">{t('cuaOff')}</option>
        <option value="true">{t('cuaOn')}</option>
      </select>
    </label>
    <label className="ds-llm-card">
      <span>{t('cuaChrome')}</span>
      <select aria-label={t('cuaChromeShort')}
        value={form.cuaChrome === undefined ? 'inherit' : String(form.cuaChrome)}
        disabled={enabled === false}
        onChange={event => onUpdate({ cuaChrome: event.target.value === 'true' })}>
        <option value="inherit" disabled>{inheritLabel('chrome')}</option>
        <option value="false">{t('cuaOff')}</option>
        <option value="true">{t('cuaOn')}</option>
      </select>
    </label>
    <label className="ds-llm-card">
      <span>{t('cuaAutoAllowApps')}</span>
      <select aria-label={t('cuaAutoAllowAppsShort')}
        value={form.cuaAutoAllowApps === undefined ? 'inherit' : String(form.cuaAutoAllowApps)}
        disabled={enabled === false}
        onChange={event => onUpdate({ cuaAutoAllowApps: event.target.value === 'true' })}>
        <option value="inherit" disabled>{inheritLabel('autoAllowApps')}</option>
        <option value="false">{t('cuaOff')}</option>
        <option value="true">{t('cuaOn')}</option>
      </select>
    </label>
    <p className="ds-llm-card__meta">{t('cuaAutoAllowAppsHint')}</p>
    <label className="ds-llm-card">
      <span>{t('cuaWindowPreview')}</span>
      <select aria-label={t('cuaWindowPreview')}
        value={String(form.cuaWindowPreview !== false)}
        disabled={enabled === false}
        onChange={event => onUpdate({ cuaWindowPreview: event.target.value === 'true' })}>
        <option value="true">{t('cuaOn')}</option>
        <option value="false">{t('cuaOff')}</option>
      </select>
    </label>
    <p className="ds-llm-card__meta">{t('cuaWindowPreviewHint')}</p>
    <p className="ds-llm-card__meta">{t('cuaVisionHint')}</p>
    {window.dsGui?.platform === 'darwin' && enabled !== false ? <SystemPermissions /> : null}
  </div>
}
