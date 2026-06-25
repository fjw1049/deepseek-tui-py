import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Info, Loader2, Mail, MessageSquare } from 'lucide-react'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'
import { FeishuChannelSetup } from './FeishuChannelSetup'
import { EmailChannelSetup } from './EmailChannelSetup'
import {
  isEmailConfigured,
  normalizePresetEmailConfig,
  parseEmailConfig,
  type EmailChannelConfig
} from '../../lib/resolve-automation-email-config'
import {
  loadChannelPanelState,
  saveChannelPanelState
} from '../../lib/channel-panel-state'

type Props = { runtimeReady: boolean }

const initialPanelState = loadChannelPanelState()

export function ChannelCenter({ runtimeReady }: Props): ReactElement {
  const { t } = useTranslation('common')

  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const [feishuConfig, setFeishuConfig] = useState<FeishuConfigV1 | null>(null)
  const [feishuOpen, setFeishuOpen] = useState(initialPanelState.feishu)

  const [emailConfig, setEmailConfig] = useState<EmailChannelConfig | null>(null)
  const [emailPasswordConfigured, setEmailPasswordConfigured] = useState(false)
  const [emailOpen, setEmailOpen] = useState(initialPanelState.email)

  const refreshFeishu = useCallback(async () => {
    const feishu = await window.dsGui.getFeishuConfig()
    setFeishuConfig(feishu.config)
  }, [])

  const refreshEmail = useCallback(async () => {
    const [configFile, secretStatus] = await Promise.all([
      window.dsGui.getDeepseekConfigFile(),
      window.dsGui.getEmailSecretStatus()
    ])
    setEmailConfig(normalizePresetEmailConfig(parseEmailConfig(configFile.content ?? '')))
    setEmailPasswordConfigured(secretStatus.passwordConfigured)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await Promise.all([refreshFeishu(), refreshEmail()])
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshEmail, refreshFeishu])

  useEffect(() => {
    saveChannelPanelState({ feishu: feishuOpen, email: emailOpen })
  }, [emailOpen, feishuOpen])

  const feishuConfigured = Boolean(feishuConfig?.appId?.trim() && feishuConfig?.appSecret?.trim())
  const emailConfigured =
    emailConfig != null && isEmailConfigured(emailConfig, { passwordConfigured: emailPasswordConfigured })

  const btnClass =
    'shrink-0 rounded-lg bg-ds-ink px-4 py-1.5 text-[13px] font-medium text-ds-card hover:opacity-80'

  return (
    <div className="ds-feature-page ds-channel-page ds-page-scroll ds-no-drag h-full overflow-auto px-8 py-10">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8 text-center">
          <h1 className="text-[26px] font-bold text-ds-ink">{t('channelCenterTitle')}</h1>
          <p className="mt-2 text-[14px] text-ds-muted">{t('channelCenterDesc')}</p>
          <p className="mt-1 text-[13px] text-ds-faint">{t('channelLocalStorageHint')}</p>
        </div>

        <div className="mb-6 flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-2.5 text-[13px] text-blue-700 dark:bg-blue-950/20 dark:text-blue-300">
          <Info className="h-4 w-4 shrink-0" />
          <span className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full ${runtimeReady ? 'bg-emerald-500' : 'bg-ds-faint'}`}
            />
            {runtimeReady ? t('channelRuntimeOnline') : t('channelRuntimeOffline')}
          </span>
        </div>

        {error ? (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-700 dark:text-red-200">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('channelLoading')}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="ds-content-card rounded-xl">
              <div className="flex items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400">
                  <MessageSquare className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold text-ds-ink">{t('channelFeishuTitle')}</h2>
                  <p className="mt-0.5 text-[13px] text-ds-muted">{t('channelFeishuDesc')}</p>
                  {feishuConfigured ? (
                    <p className="mt-0.5 text-[11px] text-ds-faint">{t('channelConfigured')}</p>
                  ) : (
                    <p className="mt-0.5 text-[11px] text-ds-faint">{t('channelNotConfigured')}</p>
                  )}
                </div>
                <button type="button" onClick={() => setFeishuOpen(!feishuOpen)} className={btnClass}>
                  {feishuOpen ? t('channelBtnCollapse') : t('channelBtnConfigure')}
                </button>
              </div>
              {feishuOpen ? (
                <div className="border-t border-ds-border-muted px-3 py-4">
                  <FeishuChannelSetup
                    runtimeReady={runtimeReady}
                    onConfigured={() => void refreshFeishu()}
                  />
                </div>
              ) : null}
            </div>

            <div className="ds-content-card rounded-xl">
              <div className="flex items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400">
                  <Mail className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold text-ds-ink">{t('channelEmailTitle')}</h2>
                  <p className="mt-0.5 text-[13px] text-ds-muted">{t('channelEmailDesc')}</p>
                  {emailConfigured ? (
                    <p className="mt-0.5 text-[11px] text-ds-faint">{t('channelConfigured')}</p>
                  ) : (
                    <p className="mt-0.5 text-[11px] text-ds-faint">{t('channelNotConfigured')}</p>
                  )}
                </div>
                <button type="button" onClick={() => setEmailOpen(!emailOpen)} className={btnClass}>
                  {emailOpen ? t('channelBtnCollapse') : t('channelBtnConfigure')}
                </button>
              </div>
              {emailOpen ? (
                <div className="border-t border-ds-border-muted px-5 py-4">
                  <EmailChannelSetup
                    runtimeReady={runtimeReady}
                    onConfigured={() => void refreshEmail()}
                  />
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
