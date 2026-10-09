import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppSettingsV1 } from '@shared/app-settings'
import { normalizeNetworkSettings, type NetworkSettings } from '@shared/network-settings'
import { FieldHelpPopover } from '../channels/FieldHelpPopover'
import { SettingsSelect } from './SettingsSelect'

export function NetworkSettingsPanel({ form, onUpdate }: {
  form: AppSettingsV1
  onUpdate: (patch: { network: NetworkSettings }) => void
}): ReactElement {
  const { t } = useTranslation('settings')
  const network = normalizeNetworkSettings(form.network)
  const savedHosts = network.bypassHosts.join('\n')
  const [hosts, setHosts] = useState(savedHosts)
  const [invalid, setInvalid] = useState(false)
  useEffect(() => { setHosts(savedHosts) }, [savedHosts])

  const commitHosts = (): void => {
    try {
      const value = normalizeNetworkSettings({
        ...network,
        bypassHosts: hosts.split('\n').filter((host) => host.trim())
      })
      setInvalid(false)
      if (JSON.stringify(value) !== JSON.stringify(network)) onUpdate({ network: value })
    } catch {
      setInvalid(true)
    }
  }

  return (
    <section className="ds-content-card mt-5 rounded-2xl" aria-labelledby="network-settings-title">
      <div className="border-b border-ds-border-muted px-5 py-3">
        <h2 id="network-settings-title" className="text-[16px] font-semibold text-ds-ink">{t('networkTitle')}</h2>
      </div>
      <div className="divide-y divide-ds-border-muted px-2 py-1">
        <div className="ds-setting-row ds-density-row flex flex-col gap-3 px-3 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-8">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1 text-[14px] font-semibold text-ds-ink">
              <label htmlFor="network-mode">{t('networkProxy')}</label>
              <FieldHelpPopover title={t('networkProxy')} intro={t('networkScope')} />
            </div>
            <p className="mt-0.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted break-keep">{t('networkDescription')}</p>
          </div>
          <div className="w-full min-w-0 sm:ml-auto sm:max-w-[210px] sm:shrink-0">
            <SettingsSelect id="network-mode" value={network.mode} onChange={(event) => {
              setInvalid(false)
              setHosts(savedHosts)
              onUpdate({ network: { ...network, mode: event.target.value as NetworkSettings['mode'] } })
            }}>
              <option value="system">{t('networkSystem')}</option>
              <option value="direct">{t('networkDirect')}</option>
            </SettingsSelect>
          </div>
        </div>
        {network.mode === 'system' && (
          <div className="ds-density-row flex flex-col gap-3 px-3 py-4">
            <div>
              <label htmlFor="network-hosts" className="text-[14px] font-semibold text-ds-ink">{t('networkBypass')}</label>
              <p id="network-hosts-hint" className="mt-0.5 text-[13px] leading-relaxed text-ds-muted">{t('networkBypassHint')}</p>
            </div>
            <textarea id="network-hosts" rows={2} value={hosts} spellCheck={false}
              aria-describedby={invalid ? 'network-hosts-hint network-hosts-error' : 'network-hosts-hint'}
              aria-invalid={invalid} placeholder="devpilot.zhonganonline.com"
              onChange={(event) => { setHosts(event.target.value); setInvalid(false) }} onBlur={commitHosts}
              className="min-h-20 w-full resize-y rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] leading-6 text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" />
            {invalid && <p id="network-hosts-error" role="alert" className="text-[12px] text-red-700 dark:text-red-300">{t('networkInvalidHost')}</p>}
          </div>
        )}
      </div>
    </section>
  )
}
