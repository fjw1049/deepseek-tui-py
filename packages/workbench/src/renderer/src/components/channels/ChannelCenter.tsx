import { useCallback, useEffect, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Info, Loader2, Mail, MessageSquare, Users } from 'lucide-react'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'
import { FeishuChannelSetup } from './FeishuChannelSetup'
import { EmailChannelSetup } from './EmailChannelSetup'
import { WecomChannelSetup } from './WecomChannelSetup'
import {
  isEmailConfigured,
  normalizePresetEmailConfig,
  parseEmailConfig,
  type EmailChannelConfig
} from '../../lib/resolve-automation-email-config'
import { loadWecomChannelState } from '../../lib/resolve-automation-wecom-config'
import {
  loadChannelPanelState,
  saveChannelPanelState
} from '../../lib/channel-panel-state'

type Props = { runtimeReady: boolean }

type ChannelCardProps = {
  icon: ReactNode
  title: string
  description: string
  configured: boolean
  open: boolean
  onToggle: () => void
  contentClassName?: string
  children: ReactNode
}

function ChannelCard({
  icon,
  title,
  description,
  configured,
  open,
  onToggle,
  contentClassName = 'px-5 py-4',
  children
}: ChannelCardProps): ReactElement {
  const { t } = useTranslation('common')

  return (
    <div className="ds-content-card ds-content-card--interactive rounded-xl">
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="flex w-full cursor-pointer items-center gap-4 px-5 py-4 text-left"
      >
        {icon}
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-ds-ink">{title}</h2>
          <p className="mt-0.5 text-[13px] text-ds-muted">{description}</p>
          {configured ? (
            <p className="mt-0.5 text-[11px] text-emerald-600 dark:text-emerald-400">
              {t('channelConfigured')}
            </p>
          ) : (
            <p className="mt-0.5 text-[11px] text-ds-faint">{t('channelNotConfigured')}</p>
          )}
        </div>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-ds-faint transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
          aria-hidden
        />
      </button>
      {open ? <div className={`border-t border-ds-border-muted ${contentClassName}`}>{children}</div> : null}
    </div>
  )
}

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

  const [wecomConfigured, setWecomConfigured] = useState(false)
  const [wecomOpen, setWecomOpen] = useState(initialPanelState.wecom)

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

  const refreshWecom = useCallback(async () => {
    const wecom = await loadWecomChannelState()
    setWecomConfigured(wecom.configured)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await Promise.all([refreshFeishu(), refreshEmail(), refreshWecom()])
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshEmail, refreshFeishu, refreshWecom])

  useEffect(() => {
    saveChannelPanelState({ feishu: feishuOpen, email: emailOpen, wecom: wecomOpen })
  }, [emailOpen, feishuOpen, wecomOpen])

  const feishuConfigured = Boolean(feishuConfig?.appId?.trim() && feishuConfig?.appSecret?.trim())
  const emailConfigured =
    emailConfig != null && isEmailConfigured(emailConfig, { passwordConfigured: emailPasswordConfigured })

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
            <ChannelCard
              icon={
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400">
                  <MessageSquare className="h-5 w-5" />
                </div>
              }
              title={t('channelFeishuTitle')}
              description={t('channelFeishuDesc')}
              configured={feishuConfigured}
              open={feishuOpen}
              onToggle={() => setFeishuOpen((value) => !value)}
              contentClassName="px-3 py-4"
            >
              <FeishuChannelSetup
                runtimeReady={runtimeReady}
                onConfigured={() => void refreshFeishu()}
              />
            </ChannelCard>

            <ChannelCard
              icon={
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400">
                  <Mail className="h-5 w-5" />
                </div>
              }
              title={t('channelEmailTitle')}
              description={t('channelEmailDesc')}
              configured={emailConfigured}
              open={emailOpen}
              onToggle={() => setEmailOpen((value) => !value)}
            >
              <EmailChannelSetup runtimeReady={runtimeReady} onConfigured={() => void refreshEmail()} />
            </ChannelCard>

            <ChannelCard
              icon={
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400">
                  <Users className="h-5 w-5" />
                </div>
              }
              title={t('channelWecomTitle')}
              description={t('channelWecomDesc')}
              configured={wecomConfigured}
              open={wecomOpen}
              onToggle={() => setWecomOpen((value) => !value)}
            >
              <WecomChannelSetup runtimeReady={runtimeReady} onConfigured={() => void refreshWecom()} />
            </ChannelCard>
          </div>
        )}
      </div>
    </div>
  )
}
