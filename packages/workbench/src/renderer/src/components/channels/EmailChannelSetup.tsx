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
      {notice ? (
        <div
          className={`rounded-lg px-3 py-2 text-[13px] ${
            notice.tone === 'error'
              ? 'bg-red-500/10 text-red-700 dark:text-red-200'
              : notice.tone === 'success'
                ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
                : 'bg-ds-subtle text-ds-muted'
          }`}
        >
          {notice.message}
        </div>
      ) : null}

      <div className="grid gap-3">
        <label className="grid gap-1">
          <span className="text-[13px] font-medium text-ds-ink">{t('channelEmailProvider')}</span>
          <select
            className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
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

        <label className="grid gap-1">
          <span className="text-[13px] font-medium text-ds-ink">{t('channelEmailMailTo')}</span>
          <input
            className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
            value={emailConfig.mailTo}
            onChange={(e) => syncUsernameFromMail(e.target.value)}
            placeholder={t('channelEmailMailToPlaceholder')}
          />
        </label>

        <label className="grid gap-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-medium text-ds-ink">{t('channelEmailAuthCode')}</span>
            <FieldHelpPopover
              title={t('channelEmailAuthCodeHelpTitle')}
              intro={t('channelEmailAuthCodeHelpIntro')}
              steps={authHelpSteps}
              ariaLabel={t('channelEmailAuthCodeHelpTitle')}
            />
          </div>
          <input
            type="password"
            className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
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

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => void handleSave()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          {t('channelEmailSave')}
        </button>
        <button
          type="button"
          disabled={testing || !configured}
          onClick={() => void handleTestSend()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink hover:bg-ds-hover disabled:opacity-50"
        >
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          {t('channelEmailTestSend')}
        </button>
      </div>
    </div>
  )
}
