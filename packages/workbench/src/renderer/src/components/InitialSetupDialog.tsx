import { type ReactElement, type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  sandboxModeForApprovalPolicy,
  type ApprovalPolicy,
  type AppSettingsV1
} from '@shared/app-settings'
import { applyTheme } from '../lib/apply-theme'
import { useChatStore } from '../store/chat-store'
import { Eye, EyeOff, ExternalLink, ChevronRight, Sparkles, KeyRound, FolderOpen, ShieldCheck } from 'lucide-react'
import { GlassSegmentedControl } from './settings/GlassSegmentedControl'

type ThemePref = AppSettingsV1['theme']
type SetupFormPatch = Partial<Omit<AppSettingsV1, 'deepseek' | 'llmProviders'>> & {
  deepseek?: Partial<AppSettingsV1['deepseek']>
  llmProviders?: AppSettingsV1['llmProviders']
}

const DEEPSEEK_USAGE_URL = 'https://platform.deepseek.com/usage'

const fieldClass =
  'w-full min-w-0 h-10 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm outline-none transition placeholder:text-ds-faint focus:border-accent/40 focus:ring-1 focus:ring-accent/30'

function Row({
  title,
  icon,
  description,
  control
}: {
  title: string
  icon?: ReactNode
  description?: ReactNode
  control: ReactNode
}): ReactElement {
  return (
    <div className="ds-guide-row">
      <div className="ds-guide-row__label">
        <div className="ds-guide-row__title">{icon ? <span className="ds-guide-row__icon" aria-hidden="true">{icon}</span> : null}{title}</div>
        {description ? <div className="ds-guide-row__desc">{description}</div> : null}
      </div>
      <div className="ds-guide-row__control">{control}</div>
    </div>
  )
}

/** First-run / quick-setup panel rendered inside Settings → setup. */
export function InitialSetupPanel(): ReactElement {
  const { t } = useTranslation('settings')
  const openSettings = useChatStore((s) => s.openSettings)
  const closeInitialSetup = useChatStore((s) => s.closeInitialSetup)
  const applyI18n = useChatStore((s) => s.applyI18nFromSettings)
  const reloadUiSettings = useChatStore((s) => s.reloadUiSettings)
  const probeRuntime = useChatStore((s) => s.probeRuntime)

  const [form, setForm] = useState<AppSettingsV1 | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [loadError, setLoadError] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [workspacePickerError, setWorkspacePickerError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadError(false)
    void Promise.resolve().then(() => window.dsGui.getSettings()).then((s) => {
      if (!cancelled) setForm(s)
    }).catch(() => {
      if (!cancelled) setLoadError(true)
    })
    return () => {
      cancelled = true
    }
  }, [loadAttempt])

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
    if (!Object.values(form.llmProviders).some((provider) => provider.apiKey.trim())) {
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
      await reloadUiSettings()
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
        {loadError ? <div role="alert" className="space-y-3 text-center"><p>{t('setupLoadError')}</p><button className="ds-guide-btn-ghost" onClick={() => setLoadAttempt((n) => n + 1)}>{t('setupRetry')}</button></div> : t('loading')}
      </div>
    )
  }

  return (
    <div className="ds-guide-sheet mx-auto w-full max-w-[880px]">
      <section className="ds-guide-panel">
        <header className="ds-guide-hero">
          <span className="ds-guide-hero__mark" aria-hidden="true"><Sparkles size={24} strokeWidth={1.6} /></span>
          <div>
            <h1 className="ds-guide-hero__title">{t('firstRunTitle')}</h1>
            <p className="ds-guide-hero__sub">{t('firstRunSubtitle')}</p>
          </div>
        </header>

        <fieldset disabled={saving} className="ds-guide-body ds-content-card rounded-2xl min-w-0">
          <Row
            title={t('apiKey')}
            icon={<KeyRound size={16} strokeWidth={1.7} />}
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
              <div className="space-y-2">
                <div className="relative w-full">
                  <input
                    type={showApiKey ? 'text' : 'password'}
                    aria-label={t('apiKey')}
                    value={form.deepseek.apiKey}
                    onChange={(e) => handleApiKeyChange(e.target.value)}
                    placeholder="sk-..."
                    className={`${fieldClass} pr-10 tracking-[0.02em]`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey((v) => !v)}
                    aria-label={showApiKey ? t('hideSecret') : t('showSecret')}
                    className="absolute right-1 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-ds-faint transition-colors hover:text-ds-muted"
                  >
                    {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <button type="button" className="ds-guide-provider-link text-[13px] text-ds-muted hover:text-accent" onClick={() => { void reloadUiSettings(); openSettings('models') }}>
                  {t('setupOtherProvider')}
                </button>
              </div>
            }
          />
          <Row
            title={t('workspaceRoot')}
            icon={<FolderOpen size={16} strokeWidth={1.7} />}
            description={
              workspacePickerError ? (
                <p className="text-[13px] leading-5 text-amber-700 dark:text-amber-300">
                  {workspacePickerError}
                </p>
              ) : undefined
            }
            control={
              <div className="flex w-full min-w-0 items-center gap-2">
                <input
                  className={`${fieldClass} flex-1`}
                  aria-label={t('workspaceRoot')}
                  value={form.workspaceRoot}
                  onChange={(e) => updateForm({ workspaceRoot: e.target.value })}
                  placeholder={t('workspaceRootPlaceholder')}
                  title={form.workspaceRoot}
                />
                <div className="shrink-0">
                  <button
                    type="button"
                    onClick={() => void pickWorkspace()}
                    className="ds-guide-directory-button"
                  >
                    {t('browse')}
                  </button>
                </div>
              </div>
            }
          />
          <Row
            title={t('approvalPolicy')}
            icon={<ShieldCheck size={16} strokeWidth={1.7} />}
            description={t(`setupApprovalHelp.${form.deepseek.approvalPolicy}`)}
            control={
              <GlassSegmentedControl
                ariaLabel={t('approvalPolicy')}
                className="w-full"
                segmentClassName="px-2.5 py-1.5"
                value={form.deepseek.approvalPolicy}
                items={[
                  { value: 'on-request', label: t('firstRunApprovalOnRequest') },
                  { value: 'untrusted', label: t('firstRunApprovalUntrusted') },
                  { value: 'auto', label: t('firstRunApprovalAuto') },
                  ...(form.deepseek.approvalPolicy === 'never' || form.deepseek.approvalPolicy === 'suggest'
                    ? [{ value: form.deepseek.approvalPolicy, label: t(form.deepseek.approvalPolicy === 'never' ? 'approvalNever' : 'approvalSuggest') }] : [])
                ]}
                onChange={handleApprovalChange}
              />
            }
          />
          <details className="ds-guide-preferences">
            <summary><ChevronRight size={15} />{t('setupPreferences')}</summary>
          <Row
            title={t('language')}
            control={
              <GlassSegmentedControl
                ariaLabel={t('language')}
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
                ariaLabel={t('theme')}
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
          </details>
        </fieldset>

        {error ? (
          <div role="alert" className="mx-4 mb-2 rounded-xl border border-[var(--ds-danger)]/20 bg-[var(--ds-danger-soft)] px-4 py-3 text-[13px] text-[var(--ds-danger)]">
            {error}
          </div>
        ) : null}

        <div className="ds-guide-actions">
          <button type="button" disabled={saving} onClick={handleClose} className="ds-guide-btn-ghost">
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
