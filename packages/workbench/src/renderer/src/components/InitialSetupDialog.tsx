import { type ReactElement, type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  sandboxModeForApprovalPolicy,
  type ApprovalPolicy,
  type AppSettingsV1
} from '@shared/app-settings'
import { applyTheme } from '../lib/apply-theme'
import { useChatStore } from '../store/chat-store'
import { Eye, EyeOff, ExternalLink, Rocket } from 'lucide-react'
import { GlassSegmentedControl } from './settings/GlassSegmentedControl'
import { settingsBlockButtonClass } from './settings/SettingsActionToolbar'

type ThemePref = AppSettingsV1['theme']
type SetupFormPatch = Partial<Omit<AppSettingsV1, 'deepseek' | 'llmProviders'>> & {
  deepseek?: Partial<AppSettingsV1['deepseek']>
  llmProviders?: AppSettingsV1['llmProviders']
}

const DEEPSEEK_USAGE_URL = 'https://platform.deepseek.com/usage'

const fieldClass =
  'w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3.5 py-3 text-[15px] text-ds-ink shadow-sm outline-none transition placeholder:text-ds-faint focus:border-accent/40 focus:ring-1 focus:ring-accent/30'

function Row({
  title,
  description,
  control
}: {
  title: string
  description?: ReactNode
  control: ReactNode
}): ReactElement {
  return (
    <div className="ds-guide-row">
      <div className="ds-guide-row__label">
        <div className="ds-guide-row__title">{title}</div>
        {description ? <div className="ds-guide-row__desc">{description}</div> : null}
      </div>
      <div className="ds-guide-row__control">{control}</div>
    </div>
  )
}

/** First-run / quick-setup panel rendered inside Settings → setup. */
export function InitialSetupPanel(): ReactElement {
  const { t } = useTranslation('settings')
  const closeInitialSetup = useChatStore((s) => s.closeInitialSetup)
  const applyI18n = useChatStore((s) => s.applyI18nFromSettings)
  const reloadUiSettings = useChatStore((s) => s.reloadUiSettings)
  const probeRuntime = useChatStore((s) => s.probeRuntime)

  const [form, setForm] = useState<AppSettingsV1 | null>(null)
  const [showApiKey, setShowApiKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [workspacePickerError, setWorkspacePickerError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (typeof window.dsGui === 'undefined') return
    void window.dsGui.getSettings().then((s) => {
      if (!cancelled) setForm(s)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const updateForm = (patch: SetupFormPatch) => {
    if (!form) return
    const next: AppSettingsV1 = {
      ...form,
      ...patch,
      deepseek: { ...form.deepseek, ...(patch.deepseek ?? {}) },
      llmProviders: patch.llmProviders ?? form.llmProviders
    }
    setForm(next)
  }

  const handleThemeChange = (theme: ThemePref) => {
    updateForm({ theme })
    applyTheme(theme)
  }

  const handleApprovalChange = (approvalPolicy: ApprovalPolicy) => {
    updateForm({
      deepseek: {
        approvalPolicy,
        sandboxMode: sandboxModeForApprovalPolicy(approvalPolicy)
      }
    })
  }

  const handleApiKeyChange = (apiKey: string) => {
    if (!form) return
    updateForm({
      deepseek: { apiKey },
      llmProviders: {
        ...form.llmProviders,
        deepseek: { ...form.llmProviders.deepseek, apiKey }
      }
    })
  }

  const handleClose = () => {
    setError(null)
    closeInitialSetup()
    void reloadUiSettings()
  }

  const handleOpenOfficialApiPage = () => {
    if (typeof window.dsGui?.openExternal !== 'function') return
    void window.dsGui.openExternal(DEEPSEEK_USAGE_URL)
  }

  const pickWorkspace = async (): Promise<void> => {
    if (!form) return
    try {
      setWorkspacePickerError(null)
      if (typeof window.dsGui?.pickWorkspaceDirectory !== 'function') {
        throw new Error('workspace:pick-directory unavailable')
      }
      const picked = await window.dsGui.pickWorkspaceDirectory(form.workspaceRoot || undefined)
      if (!picked.canceled && picked.path) {
        updateForm({ workspaceRoot: picked.path })
      }
    } catch (e) {
      setWorkspacePickerError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleSave = async () => {
    if (!form) return
    if (!form.deepseek.apiKey.trim()) {
      setError(t('firstRunApiKeyValidation'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (typeof window.dsGui === 'undefined') throw new Error('Preload bridge missing')
      const payload: AppSettingsV1 = {
        ...form,
        deepseek: {
          ...form.deepseek,
          sandboxMode: sandboxModeForApprovalPolicy(form.deepseek.approvalPolicy)
        },
        llmProviders: {
          ...form.llmProviders,
          deepseek: {
            ...form.llmProviders.deepseek,
            apiKey: form.deepseek.apiKey
          }
        }
      }
      const next = await window.dsGui.setSettings(payload)
      setForm(next)
      await applyI18n(next.locale)
      void reloadUiSettings()
      void probeRuntime('background')
      closeInitialSetup()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!form) {
    return (
      <div className="mx-auto flex max-w-[1000px] justify-center py-10 text-sm text-ds-muted">
        {t('loading')}
      </div>
    )
  }

  const approvalValue: ApprovalPolicy =
    form.deepseek.approvalPolicy === 'suggest' ? 'on-request' : form.deepseek.approvalPolicy

  return (
    <div className="ds-guide-sheet mx-auto max-w-[1000px]">
      <section className="ds-guide-panel">
        <header className="ds-guide-hero">
          <div className="ds-guide-hero__grid" aria-hidden />
          <div className="ds-guide-hero__blob ds-guide-hero__blob--a" aria-hidden />
          <div className="ds-guide-hero__blob ds-guide-hero__blob--b" aria-hidden />
          <div className="ds-guide-hero__orbit" aria-hidden>
            <div className="ds-guide-hero__orbit-ring">
              <span className="ds-guide-hero__orbit-dot" />
            </div>
            <div className="ds-guide-hero__orbit-ring ds-guide-hero__orbit-ring--inner" />
          </div>
          <svg className="ds-guide-hero__trail" viewBox="0 0 260 42" fill="none" aria-hidden>
            <path
              className="ds-guide-hero__trail-path"
              d="M6 30 C 54 30, 78 8, 124 12 S 190 36, 246 14"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
            <path
              d="M238 8 L250 14 L238 20"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="124" cy="12" r="2.5" fill="currentColor" opacity="0.55" />
          </svg>
          <div className="ds-guide-hero__body">
            <div className="ds-guide-hero__pad" aria-hidden>
              <Rocket className="ds-guide-hero__pad-rocket h-8 w-8" strokeWidth={1.9} />
            </div>
            <div className="min-w-0">
              <div className="ds-guide-hero__meta">{t('firstRunMeta')}</div>
              <h1 className="ds-guide-hero__title">{t('setup')}</h1>
              <p className="ds-guide-hero__sub">{t('firstRunSubtitle')}</p>
            </div>
          </div>
        </header>

        <div className="ds-guide-body divide-y divide-ds-border-muted">
          <div className="ds-guide-section">{t('firstRunSectionUi')}</div>
          <Row
            title={t('language')}
            control={
              <GlassSegmentedControl
                className="w-full"
                value={form.locale}
                items={[
                  { value: 'en', label: 'English' },
                  { value: 'zh', label: '简体中文' }
                ]}
                onChange={(locale) => {
                  updateForm({ locale })
                  void applyI18n(locale)
                }}
              />
            }
          />
          <Row
            title={t('theme')}
            control={
              <GlassSegmentedControl
                className="w-full"
                value={form.theme}
                items={[
                  { value: 'light', label: t('themeLight') },
                  { value: 'dark', label: t('themeDark') },
                  { value: 'system', label: t('themeSystem') }
                ]}
                onChange={handleThemeChange}
              />
            }
          />
          <div className="ds-guide-section">{t('firstRunSectionStart')}</div>
          <Row
            title={t('apiKey')}
            description={
              <button
                type="button"
                onClick={handleOpenOfficialApiPage}
                className="inline-flex items-center gap-1 text-[13px] font-medium text-accent transition hover:brightness-110"
              >
                <span>{t('firstRunBuyApiAction')}</span>
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
            }
            control={
              <div className="relative w-full">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={form.deepseek.apiKey}
                  onChange={(e) => handleApiKeyChange(e.target.value)}
                  placeholder="sk-..."
                  className={`${fieldClass} pr-10 tracking-[0.02em]`}
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey((v) => !v)}
                  aria-label={showApiKey ? t('hideSecret') : t('showSecret')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ds-faint transition-colors hover:text-ds-muted"
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            }
          />
          <Row
            title={t('workspaceRoot')}
            description={
              workspacePickerError ? (
                <p className="text-[13px] leading-5 text-amber-700 dark:text-amber-300">
                  {workspacePickerError}
                </p>
              ) : undefined
            }
            control={
              <div className="flex w-full min-w-0 items-center gap-3">
                <input
                  className={`${fieldClass} flex-1`}
                  value={form.workspaceRoot}
                  onChange={(e) => updateForm({ workspaceRoot: e.target.value })}
                  placeholder={t('workspaceRootPlaceholder')}
                  title={form.workspaceRoot}
                />
                <div className="w-[7.5rem] shrink-0">
                  <button
                    type="button"
                    onClick={() => void pickWorkspace()}
                    className={settingsBlockButtonClass()}
                  >
                    {t('browse')}
                  </button>
                </div>
              </div>
            }
          />
          <Row
            title={t('approvalPolicy')}
            control={
              <GlassSegmentedControl
                className="w-full"
                segmentClassName="px-2.5 py-1.5"
                value={
                  approvalValue === 'never' || approvalValue === 'suggest'
                    ? 'on-request'
                    : approvalValue
                }
                items={[
                  { value: 'on-request', label: t('firstRunApprovalOnRequest') },
                  { value: 'untrusted', label: t('firstRunApprovalUntrusted') },
                  { value: 'auto', label: t('firstRunApprovalAuto') }
                ]}
                onChange={handleApprovalChange}
              />
            }
          />
        </div>

        {error ? (
          <div className="mx-4 mb-2 rounded-xl border border-[var(--ds-danger)]/20 bg-[var(--ds-danger-soft)] px-4 py-3 text-[13px] text-[var(--ds-danger)]">
            {error}
          </div>
        ) : null}

        <div className="ds-guide-actions">
          <button type="button" onClick={handleClose} className="ds-guide-btn-ghost">
            {t('firstRunClose')}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            className="ds-guide-btn-primary"
          >
            {saving ? t('firstRunSaving') : t('firstRunSave')}
          </button>
        </div>
      </section>
    </div>
  )
}

/** @deprecated Use InitialSetupPanel; kept for any lingering imports. */
export const InitialSetupDialog = InitialSetupPanel
