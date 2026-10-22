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
    <p className="ds-llm-card__meta">{t('cuaVisionHint')}</p>
  </div>
}
