import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save, Send } from 'lucide-react'
import { upsertTomlSections } from '@shared/toml-section'
import {
  DEFAULT_EMAIL_PASSWORD_ENV,
  EMAIL_PROVIDER_IDS,
  EMAIL_PROVIDER_LABEL_KEYS,
  type EmailProviderId
} from '@shared/email-channel'
import {
  EMPTY_EMAIL_CONFIG,
  isEmailConfigured,
  normalizePresetEmailConfig,
  parseEmailConfig,
  resolveSimpleEmailProvider,
  type EmailChannelConfig
} from '../../lib/resolve-automation-email-config'
import { FieldHelpPopover } from './FieldHelpPopover'
import {
  CHANNEL_ACTIONS,
  CHANNEL_BTN_ICON,
  CHANNEL_CONTROL,
  CHANNEL_FIELD,
  CHANNEL_LABEL,
  CHANNEL_PRIMARY_BTN,
  CHANNEL_SECONDARY_BTN,
  channelNoticeClass
} from './channel-setup-ui'

type Props = {
  runtimeReady: boolean
  onConfigured: () => void
}

type Notice = { tone: 'success' | 'error' | 'info'; message: string }

const SIMPLE_PROVIDER_IDS = EMAIL_PROVIDER_IDS.filter((id) => id !== 'custom')

const PROVIDER_OPTIONS = SIMPLE_PROVIDER_IDS.map((id) => ({
  id,
  labelKey: EMAIL_PROVIDER_LABEL_KEYS[id]
}))

const AUTH_CODE_HELP_KEYS: Record<EmailProviderId, string> = {
  '163': 'channelEmailAuthCodeHelp163',
  qq: 'channelEmailAuthCodeHelpQq',
  gmail: 'channelEmailAuthCodeHelpGmail',
  outlook: 'channelEmailAuthCodeHelpOutlook',
  custom: 'channelEmailAuthCodeHelp163'
}

export function EmailChannelSetup({ runtimeReady, onConfigured }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [emailConfig, setEmailConfig] = useState<EmailChannelConfig>(EMPTY_EMAIL_CONFIG)
  const [configContent, setConfigContent] = useState('')
  const [authCode, setAuthCode] = useState('')
  const [passwordConfigured, setPasswordConfigured] = useState(false)
  const [secureStorageAvailable, setSecureStorageAvailable] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)

  const configured = isEmailConfigured(emailConfig, { passwordConfigured })
  const activeProvider = resolveSimpleEmailProvider(emailConfig)
  const authHelpSteps = t(AUTH_CODE_HELP_KEYS[activeProvider]).split('\n').filter(Boolean)

  const loadState = useCallback(async () => {
    try {
      const [configFile, secretStatus] = await Promise.all([
        window.dsGui.getDeepseekConfigFile(),
        window.dsGui.getEmailSecretStatus()
      ])
      const content = configFile.content ?? ''
      setConfigContent(content)
      setEmailConfig(normalizePresetEmailConfig(parseEmailConfig(content)))
      setPasswordConfigured(secretStatus.passwordConfigured)
      setSecureStorageAvailable(secretStatus.secureStorageAvailable)
    } catch (err) {
      setNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    }
  }, [])

  useEffect(() => {
    void loadState()
  }, [loadState])

  const applyProvider = (provider: EmailProviderId): void => {
    setEmailConfig((current) => normalizePresetEmailConfig({ ...current, provider }))
  }

  const buildTomlPatch = (config: EmailChannelConfig) => ({
    automation: { mail_to: config.mailTo.trim() },
    'automation.email': {
      smtp_host: config.smtpHost.trim(),
      smtp_port: Number(config.smtpPort) || 587,
      smtp_ssl: config.smtpSsl === 'true',
      smtp_starttls: config.smtpStarttls === 'true',
      username: config.username.trim(),
      from_addr: config.fromAddr.trim() || config.username.trim(),
      password_env: DEFAULT_EMAIL_PASSWORD_ENV
    }
  })

  const handleSave = async (): Promise<void> => {
    setSaving(true)
    setNotice(null)
    try {
      const trimmedAuth = authCode.trim()
      if (trimmedAuth) {
        if (!secureStorageAvailable) {
          setNotice({ tone: 'error', message: t('channelEmailSecureStorageUnavailable') })
          return
        }
        await window.dsGui.setEmailSecret(trimmedAuth)
        setPasswordConfigured(true)
        setAuthCode('')
      } else if (!passwordConfigured) {
        setNotice({ tone: 'error', message: t('channelEmailAuthCodeRequired') })
        return
      }

      const normalized = normalizePresetEmailConfig(emailConfig)
      const updated = upsertTomlSections(configContent, buildTomlPatch(normalized))
      await window.dsGui.setDeepseekConfigFile(updated)
      setConfigContent(updated)
      const secretStatus = await window.dsGui.getEmailSecretStatus()
      setPasswordConfigured(secretStatus.passwordConfigured)
      setEmailConfig(normalizePresetEmailConfig(parseEmailConfig(updated)))
      onConfigured()
      setNotice({ tone: 'success', message: t('channelEmailSaved') })
    } catch (err) {
      setNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    } finally {
      setSaving(false)
    }
  }

  const handleTestSend = async (): Promise<void> => {
    if (!configured) {
      setNotice({ tone: 'error', message: t('channelEmailSaveBeforeTest') })
      return
    }
    if (!runtimeReady) {
      setNotice({ tone: 'info', message: t('channelEmailNeedRuntime') })
      return
    }
    setTesting(true)
    setNotice(null)
    try {
      const raw = await window.dsGui.runtimeRequest(
        '/v1/automation/email/test-send',
        'POST',
        JSON.stringify({
          to_addr: emailConfig.mailTo.trim(),
          subject: t('channelEmailTestSubject'),
          text: t('channelEmailTestBody')
        })
      )
      if (!raw.ok) {
        let message = `HTTP ${raw.status}`
        try {
          const parsed = JSON.parse(raw.body) as { detail?: string; message?: string }
          message = parsed.detail ?? parsed.message ?? message
        } catch {
          if (raw.body.trim()) message = raw.body.trim().slice(0, 240)
        }
        setNotice({ tone: 'error', message })
        return
      }
      setNotice({ tone: 'success', message: t('channelEmailTestOk') })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setTesting(false)
    }
  }

  const syncUsernameFromMail = (mailTo: string): void => {
    setEmailConfig((current) =>
      normalizePresetEmailConfig({
        ...current,
        mailTo,
        username: mailTo.includes('@') ? mailTo : current.username,
        fromAddr: mailTo.includes('@') ? mailTo : current.fromAddr
      })
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}

      <div className="grid gap-3">
        <label className={CHANNEL_FIELD}>
          <span className={CHANNEL_LABEL}>{t('channelEmailProvider')}</span>
          <select
            className={CHANNEL_CONTROL}
            value={activeProvider}
            onChange={(e) => applyProvider(e.target.value as EmailProviderId)}
          >
            {PROVIDER_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {t(option.labelKey)}
              </option>
            ))}
          </select>
        </label>

        <label className={CHANNEL_FIELD}>
          <span className={CHANNEL_LABEL}>{t('channelEmailMailTo')}</span>
          <input
            className={CHANNEL_CONTROL}
            value={emailConfig.mailTo}
            onChange={(e) => syncUsernameFromMail(e.target.value)}
            placeholder={t('channelEmailMailToPlaceholder')}
          />
        </label>

        <label className={CHANNEL_FIELD}>
          <div className="flex items-center gap-1.5">
            <span className={CHANNEL_LABEL}>{t('channelEmailAuthCode')}</span>
            <FieldHelpPopover
              title={t('channelEmailAuthCodeHelpTitle')}
              intro={t('channelEmailAuthCodeHelpIntro')}
              steps={authHelpSteps}
              ariaLabel={t('channelEmailAuthCodeHelpTitle')}
            />
          </div>
          <input
            type="password"
            className={CHANNEL_CONTROL}
            value={authCode}
            onChange={(e) => setAuthCode(e.target.value)}
            placeholder={
              passwordConfigured
                ? t('channelEmailAuthCodeSavedPlaceholder')
                : t('channelEmailAuthCodePlaceholder')
            }
            autoComplete="off"
          />
        </label>
      </div>

      <div className={CHANNEL_ACTIONS}>
        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className={CHANNEL_PRIMARY_BTN}
        >
          {saving ? (
            <Loader2 className={`${CHANNEL_BTN_ICON} animate-spin`} />
          ) : (
            <Save className={CHANNEL_BTN_ICON} />
          )}
          {t('channelEmailSave')}
        </button>
        <button
          type="button"
          disabled={testing || !configured}
          onClick={() => void handleTestSend()}
          className={CHANNEL_SECONDARY_BTN}
        >
          {testing ? (
            <Loader2 className={`${CHANNEL_BTN_ICON} animate-spin`} />
          ) : (
            <Send className={CHANNEL_BTN_ICON} />
          )}
          {t('channelEmailTestSend')}
        </button>
      </div>
    </div>
  )
}
