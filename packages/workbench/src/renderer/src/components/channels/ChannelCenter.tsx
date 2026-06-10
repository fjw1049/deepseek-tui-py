import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Info, Loader2, Mail, MessageSquare, Save } from 'lucide-react'
import type { AppSettingsV1, ClawSettingsPatchV1 } from '@shared/app-settings'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'
import { upsertTomlSections } from '@shared/toml-section'
import { ClawFeishuSection } from '../settings/ClawFeishuSection'
import {
  EMPTY_EMAIL_CONFIG,
  isEmailConfigured,
  parseEmailConfig,
  type EmailChannelConfig
} from '../../lib/resolve-automation-email-config'

type Props = { runtimeReady: boolean }

function mergeClaw(form: AppSettingsV1, patch: ClawSettingsPatchV1): AppSettingsV1 {
  return {
    ...form,
    claw: {
      ...form.claw,
      ...patch,
      skills: { ...form.claw.skills, ...patch.skills },
      im: { ...form.claw.im, ...patch.im },
      channels: patch.channels
        ? (patch.channels as AppSettingsV1['claw']['channels'])
        : form.claw.channels,
      tasks: patch.tasks ? (patch.tasks as AppSettingsV1['claw']['tasks']) : form.claw.tasks
    }
  }
}

function maskStr(value: string, head = 4, tail = 4): string {
  const s = value.trim()
  if (!s) return ''
  if (s.length <= head + tail) return '••••••'
  return `${s.slice(0, head)}••••${s.slice(-tail)}`
}

export function ChannelCenter({ runtimeReady }: Props): ReactElement {
  const { t } = useTranslation('common')

  const [form, setForm] = useState<AppSettingsV1 | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const [feishuConfig, setFeishuConfig] = useState<FeishuConfigV1 | null>(null)
  const [feishuOpen, setFeishuOpen] = useState(false)

  const [emailConfig, setEmailConfig] = useState<EmailChannelConfig>(EMPTY_EMAIL_CONFIG)
  const [configContent, setConfigContent] = useState('')
  const [emailOpen, setEmailOpen] = useState(false)
  const [emailSaving, setEmailSaving] = useState(false)
  const [emailNotice, setEmailNotice] = useState<{
    tone: 'success' | 'error'
    message: string
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [settings, feishu, configFile] = await Promise.all([
          window.dsGui.getSettings(),
          window.dsGui.getFeishuConfig(),
          window.dsGui.getDeepseekConfigFile()
        ])
        if (cancelled) return
        setForm(settings)
        setFeishuConfig(feishu.config)
        const content = configFile.content ?? ''
        setConfigContent(content)
        setEmailConfig(parseEmailConfig(content))
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const onClawPatch = useCallback((patch: ClawSettingsPatchV1): void => {
    setForm((current) => {
      if (!current) return current
      const next = mergeClaw(current, patch)
      void window.dsGui
        .setSettings(next)
        .then(setForm)
        .catch((reason) => setError(String(reason)))
      return next
    })
  }, [])

  const handleEmailSave = async (): Promise<void> => {
    setEmailSaving(true)
    setEmailNotice(null)
    try {
      const updated = upsertTomlSections(configContent, {
        automation: { mail_to: emailConfig.mailTo },
        'automation.email': {
          smtp_host: emailConfig.smtpHost,
          smtp_port: Number(emailConfig.smtpPort) || 587,
          smtp_starttls: emailConfig.smtpStarttls === 'true',
          username: emailConfig.username,
          from_addr: emailConfig.fromAddr,
          password_env: emailConfig.passwordEnv
        }
      })
      await window.dsGui.setDeepseekConfigFile(updated)
      setConfigContent(updated)
      setEmailNotice({ tone: 'success', message: t('channelEmailSaved') })
    } catch (err) {
      setEmailNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    } finally {
      setEmailSaving(false)
    }
  }

  const feishuConfigured = Boolean(feishuConfig?.appId || feishuConfig?.chatId)
  const emailConfigured = isEmailConfigured(emailConfig)

  const btnClass =
    'shrink-0 rounded-lg bg-ds-ink px-4 py-1.5 text-[13px] font-medium text-ds-card hover:opacity-80'

  return (
    <div className="ds-feature-page ds-channel-page ds-page-scroll ds-no-drag h-full overflow-auto px-8 py-10">
      <div className="mx-auto max-w-3xl">
        {/* ── Centered header ── */}
        <div className="mb-8 text-center">
          <h1 className="text-[26px] font-bold text-ds-ink">{t('channelCenterTitle')}</h1>
          <p className="mt-2 text-[14px] text-ds-muted">{t('channelCenterDesc')}</p>
          <p className="mt-1 text-[13px] text-ds-faint">{t('channelLocalStorageHint')}</p>
        </div>

        {/* ── Runtime status banner ── */}
        <div className="mb-6 flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-2.5 text-[13px] text-blue-700 dark:bg-blue-950/20 dark:text-blue-300">
          <Info className="h-4 w-4 shrink-0" />
          <span className="flex items-center gap-1.5">
            <span
              className={`inline-block h-2 w-2 rounded-full ${runtimeReady ? 'bg-emerald-500' : 'bg-ds-faint'}`}
            />
            {runtimeReady ? t('channelRuntimeOnline') : t('channelRuntimeOffline')}
          </span>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-700 dark:text-red-200">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('channelLoading')}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* ── Feishu row ── */}
            <div className="ds-content-card rounded-xl">
              <div className="flex items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400">
                  <MessageSquare className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold text-ds-ink">
                    {t('channelFeishuTitle')}
                  </h2>
                  <p className="mt-0.5 text-[13px] text-ds-muted">{t('channelFeishuDesc')}</p>
                  {feishuConfigured && feishuConfig?.appId && (
                    <p className="mt-0.5 font-mono text-[11px] text-ds-faint">
                      App ID: {maskStr(feishuConfig.appId)}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setFeishuOpen(!feishuOpen)}
                  className={btnClass}
                >
                  {feishuOpen ? t('channelBtnCollapse') : t('channelBtnConfigure')}
                </button>
              </div>
              {feishuOpen && form && (
                <div className="border-t border-ds-border-muted px-3 py-4">
                  <ClawFeishuSection
                    form={form}
                    runtimeReady={runtimeReady}
                    runtimePort={form.deepseek.port}
                    onClawPatch={onClawPatch}
                  />
                </div>
              )}
            </div>

            {/* ── Email row ── */}
            <div className="ds-content-card rounded-xl">
              <div className="flex items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400">
                  <Mail className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold text-ds-ink">
                    {t('channelEmailTitle')}
                  </h2>
                  <p className="mt-0.5 text-[13px] text-ds-muted">{t('channelEmailDesc')}</p>
                  {emailConfigured && (
                    <p className="mt-0.5 font-mono text-[11px] text-ds-faint">
                      {emailConfig.mailTo}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setEmailOpen(!emailOpen)}
                  className={btnClass}
                >
                  {emailOpen ? t('channelBtnCollapse') : t('channelBtnConfigure')}
                </button>
              </div>
              {emailOpen && (
                <div className="border-t border-ds-border-muted px-5 py-4">
                  {emailNotice && (
                    <div
                      className={`mb-3 rounded-lg px-3 py-2 text-[13px] ${
                        emailNotice.tone === 'error'
                          ? 'bg-red-500/10 text-red-700 dark:text-red-200'
                          : 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
                      }`}
                    >
                      {emailNotice.message}
                    </div>
                  )}
                  <div className="grid gap-3">
                    <label className="grid gap-1">
                      <span className="text-[13px] font-medium text-ds-ink">
                        {t('channelEmailMailTo')}
                      </span>
                      <input
                        className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
                        value={emailConfig.mailTo}
                        onChange={(e) =>
                          setEmailConfig((c) => ({ ...c, mailTo: e.target.value }))
                        }
                        placeholder="you@example.com"
                      />
                    </label>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1">
                        <span className="text-[13px] font-medium text-ds-ink">
                          {t('channelEmailSmtpHost')}
                        </span>
                        <input
                          className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
                          value={emailConfig.smtpHost}
                          onChange={(e) =>
                            setEmailConfig((c) => ({ ...c, smtpHost: e.target.value }))
                          }
                          placeholder="smtp.example.com"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[13px] font-medium text-ds-ink">
                          {t('channelEmailSmtpPort')}
                        </span>
                        <input
                          type="number"
                          className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
                          value={emailConfig.smtpPort}
                          onChange={(e) =>
                            setEmailConfig((c) => ({ ...c, smtpPort: e.target.value }))
                          }
                        />
                      </label>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1">
                        <span className="text-[13px] font-medium text-ds-ink">
                          {t('channelEmailUsername')}
                        </span>
                        <input
                          className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
                          value={emailConfig.username}
                          onChange={(e) =>
                            setEmailConfig((c) => ({ ...c, username: e.target.value }))
                          }
                          placeholder="you@example.com"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[13px] font-medium text-ds-ink">
                          {t('channelEmailFromAddr')}
                        </span>
                        <input
                          className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none focus:border-accent/60"
                          value={emailConfig.fromAddr}
                          onChange={(e) =>
                            setEmailConfig((c) => ({ ...c, fromAddr: e.target.value }))
                          }
                          placeholder="noreply@example.com"
                        />
                      </label>
                    </div>
                    <label className="grid gap-1">
                      <span className="text-[13px] font-medium text-ds-ink">
                        {t('channelEmailPasswordEnv')}
                      </span>
                      <span className="text-[11px] text-ds-faint">
                        {t('channelEmailPasswordEnvHint')}
                      </span>
                      <input
                        className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 font-mono text-[13px] text-ds-ink outline-none focus:border-accent/60"
                        value={emailConfig.passwordEnv}
                        onChange={(e) =>
                          setEmailConfig((c) => ({ ...c, passwordEnv: e.target.value }))
                        }
                        placeholder="DEEPSEEK_EMAIL_PASSWORD"
                      />
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={emailConfig.smtpStarttls === 'true'}
                        onChange={(e) =>
                          setEmailConfig((c) => ({
                            ...c,
                            smtpStarttls: e.target.checked ? 'true' : 'false'
                          }))
                        }
                        className="h-4 w-4 rounded border-ds-border"
                      />
                      <span className="text-[13px] text-ds-ink">STARTTLS</span>
                    </label>
                    <div className="flex items-center gap-2 pt-1">
                      <button
                        type="button"
                        disabled={emailSaving}
                        onClick={() => void handleEmailSave()}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
                      >
                        {emailSaving ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Save className="h-3.5 w-3.5" />
                        )}
                        {t('channelEmailSave')}
                      </button>
                    </div>
                    <p className="text-[11px] text-ds-faint">{t('channelEmailTestHint')}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
