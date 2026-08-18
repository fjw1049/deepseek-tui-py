import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode
} from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  Check,
  ChevronRight,
  Eye,
  EyeOff,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
  Zap
} from 'lucide-react'
import {
  BUILTIN_ASR_PROVIDER_ID,
  BUILTIN_LLM_PROVIDER_IDS,
  BUILTIN_LLM_PROVIDERS,
  CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT,
  DEFAULT_ASR_BASE_URL,
  DEFAULT_ASR_MODEL,
  defaultAsrProviders,
  defaultLlmProviders,
  enabledLlmModelIds,
  normalizeCustomModelContextWindow,
  type AppSettingsPatch,
  type AppSettingsV1,
  type AsrProviderV1,
  type BuiltinLlmProviderId,
  type CustomEndpointV1,
  type EndpointProtocol,
  type LlmProviderConfigV1,
  type LlmProviderModelV1
} from '@shared/app-settings'
import { buildSilentWavProbeBytes } from '@shared/asr-probe-wav'
import { resolveProviderIcon, uniquifySvgIds } from '../chat/provider-icons.js'
import { useChatStore } from '../../store/chat-store'

type Props = {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}

const PROVIDER_NAME_KEY: Record<BuiltinLlmProviderId, string> = {
  deepseek: 'llmProviderDeepseek',
  kimi: 'llmProviderKimi',
  glm: 'llmProviderGlm',
  'volcengine-ark': 'llmProviderVolcengine'
}

const PROVIDER_ICON_TOKEN: Record<BuiltinLlmProviderId, string> = {
  deepseek: 'deepseek',
  kimi: 'kimi',
  glm: 'glm',
  'volcengine-ark': 'doubao'
}

type DetailTarget =
  | { kind: 'builtin'; id: BuiltinLlmProviderId }
  | { kind: 'custom'; id: string }
  | { kind: 'asr'; id: string }
  | { kind: 'add-llm' }
  | { kind: 'add-asr' }

function BrandIcon({
  token,
  size = 36
}: {
  token: string
  size?: number
}): ReactElement {
  const icon = resolveProviderIcon({ id: token })
  const isPhoto = icon.key === 'doubao'
  return (
    <span
      className={`ds-llm-brand${icon.colored ? ' is-colored' : ''}${isPhoto ? ' is-photo' : ''}`}
      style={{
        width: size,
        height: size,
        ['--ds-llm-brand-color' as string]: icon.color
      }}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: uniquifySvgIds(icon.svg) }}
    />
  )
}

function ProviderBrandIcon({
  id,
  size = 36
}: {
  id: BuiltinLlmProviderId
  size?: number
}): ReactElement {
  return <BrandIcon token={PROVIDER_ICON_TOKEN[id]} size={size} />
}

function StatusPill({ configured }: { configured: boolean }): ReactElement {
  const { t } = useTranslation('settings')
  return (
    <span className={`ds-llm-card__status ${configured ? 'ds-llm-card__status--on' : ''}`}>
      {configured ? (
        <>
          <Check className="h-3 w-3" strokeWidth={2.4} aria-hidden />
          {t('llmProviderConfigured')}
        </>
      ) : (
        t('llmProviderUnconfigured')
      )}
    </span>
  )
}

function SheetShell({
  title,
  caption,
  icon,
  onClose,
  children,
  footer
}: {
  title: string
  caption?: string
  icon: ReactElement
  onClose: () => void
  children: ReactNode
  footer: ReactNode
}): ReactElement | null {
  const { t: tCommon } = useTranslation('common')
  const [entered, setEntered] = useState(false)

  useEffect(() => {
    const id = window.requestAnimationFrame(() => setEntered(true))
    return () => window.cancelAnimationFrame(id)
  }, [])

  useEffect(() => {
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  if (typeof document === 'undefined') return null

  return createPortal(
    <div
      className={`ds-llm-sheet-backdrop ${entered ? 'ds-llm-sheet-backdrop--open' : ''}`}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`ds-llm-sheet ${entered ? 'ds-llm-sheet--open' : ''}`}
      >
        <div className="ds-llm-sheet__grabber" aria-hidden>
          <span />
        </div>
        <header className="ds-llm-sheet__header">
          <div className="ds-llm-sheet__identity">
            {icon}
            <div className="min-w-0">
              <h2 className="ds-llm-sheet__title">{title}</h2>
              {caption ? <p className="ds-llm-sheet__caption">{caption}</p> : null}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ds-llm-sheet__close"
            aria-label={tCommon('close')}
          >
            <X className="h-3.5 w-3.5" strokeWidth={2.4} />
          </button>
        </header>
        <div className="ds-llm-sheet__body">{children}</div>
        <footer className="ds-llm-sheet__footer">{footer}</footer>
      </div>
    </div>,
    document.body
  )
}

export function LlmProvidersPanel({ form, onUpdate }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const [detail, setDetail] = useState<DetailTarget | null>(null)

  const providers = form.llmProviders ?? defaultLlmProviders()
  const endpoints = form.customEndpoints ?? []
  const asrProviders = form.asrProviders?.length ? form.asrProviders : defaultAsrProviders()
  const defaultId = form.defaultLlmProviderId ?? 'deepseek'

  return (
    <section className="ds-llm-panel">
      <header className="ds-llm-panel__header">
        <h2 className="ds-llm-panel__title">{t('llmProvidersTitle')}</h2>
      </header>

      <div className="ds-llm-panel__section">
        <div className="ds-llm-panel__section-head">
          <h3 className="ds-llm-panel__section-title">{t('llmSectionLlm')}</h3>
          <button
            type="button"
            className="ds-llm-panel__add-btn"
            onClick={() => setDetail({ kind: 'add-llm' })}
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={2.2} />
            {t('llmAddProviderBtn')}
          </button>
        </div>
        <div className="ds-llm-panel__grid">
          {BUILTIN_LLM_PROVIDER_IDS.map((id) => {
            const configured = Boolean(providers[id]?.apiKey?.trim())
            const modelCount = enabledLlmModelIds(providers[id] ?? { apiKey: '', models: [] }).length
            return (
              <button
                key={id}
                type="button"
                onClick={() => setDetail({ kind: 'builtin', id })}
                className="ds-llm-card"
              >
                <ProviderBrandIcon id={id} />
                <span className="ds-llm-card__body">
                  <span className="ds-llm-card__name">{t(PROVIDER_NAME_KEY[id])}</span>
                  <span className="ds-llm-card__meta">
                    {configured
                      ? t('llmProviderModelCount', { count: modelCount })
                      : t('llmProviderConfigureHint')}
                  </span>
                </span>
                <StatusPill configured={configured} />
                <ChevronRight
                  className="ds-llm-card__chevron h-4 w-4 shrink-0"
                  strokeWidth={1.8}
                  aria-hidden
                />
              </button>
            )
          })}
          {endpoints.map((endpoint) => {
            const configured = Boolean(endpoint.apiKey.trim() && endpoint.enabled)
            const modelCount = endpoint.models.filter((model) => model.enabled).length
            return (
              <button
                key={endpoint.id}
                type="button"
                onClick={() => setDetail({ kind: 'custom', id: endpoint.id })}
                className="ds-llm-card"
              >
                <BrandIcon token="openai" />
                <span className="ds-llm-card__body">
                  <span className="ds-llm-card__name">{endpoint.name}</span>
                  <span className="ds-llm-card__meta">
                    {configured
                      ? t('llmProviderModelCount', { count: modelCount })
                      : t('llmProviderConfigureHint')}
                  </span>
                </span>
                <StatusPill configured={configured} />
                <ChevronRight
                  className="ds-llm-card__chevron h-4 w-4 shrink-0"
                  strokeWidth={1.8}
                  aria-hidden
                />
              </button>
            )
          })}
        </div>
      </div>

      <div className="ds-llm-panel__section">
        <div className="ds-llm-panel__section-head">
          <h3 className="ds-llm-panel__section-title">{t('llmSectionSpeech')}</h3>
          <button
            type="button"
            className="ds-llm-panel__add-btn"
            onClick={() => setDetail({ kind: 'add-asr' })}
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={2.2} />
            {t('asrAddProviderBtn')}
          </button>
        </div>
        <div className="ds-llm-panel__stack">
          {asrProviders.map((provider) => {
            const configured = Boolean(provider.apiKey.trim())
            const modelLabel =
              provider.models.find((model) => model.enabled)?.id ||
              provider.models[0]?.id ||
              DEFAULT_ASR_MODEL
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => setDetail({ kind: 'asr', id: provider.id })}
                className="ds-llm-card"
              >
                <BrandIcon token="glm" />
                <span className="ds-llm-card__body">
                  <span className="ds-llm-card__name">
                    {provider.id === BUILTIN_ASR_PROVIDER_ID
                      ? t('asrProviderZhipu')
                      : provider.name}
                  </span>
                  <span className="ds-llm-card__meta">
                    {configured ? modelLabel : t('llmProviderConfigureHint')}
                  </span>
                </span>
                <StatusPill configured={configured} />
                <ChevronRight
                  className="ds-llm-card__chevron h-4 w-4 shrink-0"
                  strokeWidth={1.8}
                  aria-hidden
                />
              </button>
            )
          })}
        </div>
      </div>

      {detail?.kind === 'builtin' ? (
        <BuiltinProviderDetailSheet
          providerId={detail.id}
          config={providers[detail.id]}
          onClose={() => setDetail(null)}
          onSave={(next) => {
            const patch: AppSettingsPatch = {
              llmProviders: { [detail.id]: next }
            }
            if (detail.id === 'deepseek') {
              patch.deepseek = { apiKey: next.apiKey }
            }
            const nextProviders = { ...providers, [detail.id]: next }
            const defaultStillValid = Boolean(nextProviders[defaultId]?.apiKey?.trim())
            if (next.apiKey.trim() && !defaultStillValid) {
              patch.defaultLlmProviderId = detail.id
            } else if (!next.apiKey.trim() && defaultId === detail.id) {
              patch.defaultLlmProviderId =
                BUILTIN_LLM_PROVIDER_IDS.find(
                  (id) => id !== detail.id && nextProviders[id]?.apiKey?.trim()
                ) ?? 'deepseek'
            }
            if (!next.apiKey.trim()) {
              void window.dsGui.pruneUsageProvider(detail.id).finally(() => {
                useChatStore.setState((state) => ({
                  usageRefreshKey: state.usageRefreshKey + 1
                }))
              })
            }
            onUpdate(patch)
            setDetail(null)
          }}
        />
      ) : null}

      {detail?.kind === 'custom' ? (
        <CustomProviderDetailSheet
          endpoint={endpoints.find((item) => item.id === detail.id) ?? null}
          onClose={() => setDetail(null)}
          onPatch={(next) => {
            onUpdate({
              customEndpoints: endpoints.map((item) => (item.id === next.id ? next : item))
            })
          }}
          onSave={(next) => {
            onUpdate({
              customEndpoints: endpoints.map((item) => (item.id === next.id ? next : item))
            })
            setDetail(null)
          }}
          onDelete={(id) => {
            void window.dsGui.pruneUsageProvider(id).finally(() => {
              useChatStore.setState((state) => ({
                usageRefreshKey: state.usageRefreshKey + 1
              }))
            })
            onUpdate({ customEndpoints: endpoints.filter((item) => item.id !== id) })
            setDetail(null)
          }}
        />
      ) : null}

      {detail?.kind === 'add-llm' ? (
        <AddLlmProviderSheet
          endpoints={endpoints}
          onClose={() => setDetail(null)}
          onSave={(endpoint) => {
            onUpdate({ customEndpoints: [...endpoints, endpoint] })
            setDetail(null)
          }}
        />
      ) : null}

      {detail?.kind === 'asr' ? (
        <AsrProviderDetailSheet
          provider={asrProviders.find((item) => item.id === detail.id) ?? null}
          onClose={() => setDetail(null)}
          onPatch={(next) => {
            onUpdate({
              asrProviders: asrProviders.map((item) => (item.id === next.id ? next : item))
            })
          }}
          onSave={(next) => {
            onUpdate({
              asrProviders: asrProviders.map((item) => (item.id === next.id ? next : item))
            })
            setDetail(null)
          }}
          onDelete={
            detail.id === BUILTIN_ASR_PROVIDER_ID
              ? undefined
              : (id) => {
                  onUpdate({
                    asrProviders: asrProviders.filter((item) => item.id !== id)
                  })
                  setDetail(null)
                }
          }
        />
      ) : null}

      {detail?.kind === 'add-asr' ? (
        <AddAsrProviderSheet
          providers={asrProviders}
          onClose={() => setDetail(null)}
          onSave={(provider) => {
            onUpdate({ asrProviders: [...asrProviders, provider] })
            setDetail(null)
          }}
        />
      ) : null}

    </section>
  )
}

function uniqueSlug(base: string, used: Set<string>): string {
  let id = base || 'provider'
  let suffix = 2
  while (used.has(id)) {
    id = `${base}-${suffix}`
    suffix += 1
  }
  return id
}

function AddLlmProviderSheet({
  endpoints,
  onClose,
  onSave
}: {
  endpoints: CustomEndpointV1[]
  onClose: () => void
  onSave: (endpoint: CustomEndpointV1) => void
}): ReactElement | null {
  const { t } = useTranslation('settings')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [protocol, setProtocol] = useState<EndpointProtocol>('openai')
  const [modelId, setModelId] = useState('')
  const [showKey, setShowKey] = useState(false)

  const canSave = Boolean(
    name.trim() && baseUrl.trim() && apiKey.trim() && modelId.trim()
  )

  return (
    <SheetShell
      title={t('llmAddProviderBtn')}
      caption={t('llmAddProviderHint')}
      icon={<BrandIcon token="openai" size={40} />}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="ds-llm-sheet__btn">
            {t('llmProviderCancel')}
          </button>
          <button
            type="button"
            disabled={!canSave}
            onClick={() => {
              if (!canSave) return
              const slug =
                name
                  .trim()
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, '-')
                  .replace(/^-|-$/g, '') || 'endpoint'
              const used = new Set<string>([
                ...BUILTIN_LLM_PROVIDER_IDS,
                ...endpoints.map((item) => item.id)
              ])
              const trimmedModel = modelId.trim()
              onSave({
                id: uniqueSlug(slug, used),
                name: name.trim(),
                protocol,
                baseUrl: baseUrl.trim(),
                apiKey: apiKey.trim(),
                enabled: true,
                models: [
                  {
                    id: trimmedModel,
                    enabled: true,
                    contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT,
                    testStatus: 'untested'
                  }
                ]
              })
            }}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--primary"
          >
            {t('saveEndpointBtn')}
          </button>
        </>
      }
    >
      <div className="ds-llm-inset">
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointNameLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('endpointNamePlaceholder')}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointUrlLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={t('endpointUrlPlaceholder')}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('llmApiKey')}</div>
          <div className="ds-llm-inset__secret">
            <input
              type={showKey ? 'text' : 'password'}
              className="ds-llm-inset__input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-…"
            />
            <button type="button" className="ds-llm-inset__eye" onClick={() => setShowKey((v) => !v)}>
              {showKey ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
            </button>
          </div>
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointProtocolLabel')}</div>
          <select
            className="ds-llm-inset__input"
            value={protocol}
            onChange={(e) => setProtocol(e.target.value as EndpointProtocol)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('llmModelIdLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder={t('llmAddModelPlaceholder')}
          />
        </div>
      </div>
    </SheetShell>
  )
}

function AddAsrProviderSheet({
  providers,
  onClose,
  onSave
}: {
  providers: AsrProviderV1[]
  onClose: () => void
  onSave: (provider: AsrProviderV1) => void
}): ReactElement | null {
  const { t } = useTranslation('settings')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState(DEFAULT_ASR_BASE_URL)
  const [apiKey, setApiKey] = useState('')
  const [modelId, setModelId] = useState(DEFAULT_ASR_MODEL)
  const [showKey, setShowKey] = useState(false)
  const canSave = Boolean(
    name.trim() && baseUrl.trim() && apiKey.trim() && modelId.trim()
  )

  return (
    <SheetShell
      title={t('asrAddProviderBtn')}
      caption={t('asrAddProviderHint')}
      icon={<BrandIcon token="glm" size={40} />}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className="ds-llm-sheet__btn">
            {t('llmProviderCancel')}
          </button>
          <button
            type="button"
            disabled={!canSave}
            onClick={() => {
              if (!canSave) return
              const slug =
                name
                  .trim()
                  .toLowerCase()
                  .replace(/[^a-z0-9]+/g, '-')
                  .replace(/^-|-$/g, '') || 'asr'
              const used = new Set(providers.map((item) => item.id))
              const trimmedModel = modelId.trim()
              onSave({
                id: uniqueSlug(slug, used),
                name: name.trim(),
                baseUrl: baseUrl.trim() || DEFAULT_ASR_BASE_URL,
                apiKey: apiKey.trim(),
                models: [{ id: trimmedModel, enabled: true }]
              })
            }}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--primary"
          >
            {t('saveEndpointBtn')}
          </button>
        </>
      }
    >
      <div className="ds-llm-inset">
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointNameLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('endpointNamePlaceholder')}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('asrBaseUrl')}</div>
          <input
            className="ds-llm-inset__input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={DEFAULT_ASR_BASE_URL}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('asrApiKey')}</div>
          <div className="ds-llm-inset__secret">
            <input
              type={showKey ? 'text' : 'password'}
              className="ds-llm-inset__input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-…"
            />
            <button type="button" className="ds-llm-inset__eye" onClick={() => setShowKey((v) => !v)}>
              {showKey ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
            </button>
          </div>
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('asrModel')}</div>
          <input
            className="ds-llm-inset__input"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder={DEFAULT_ASR_MODEL}
            title={t('asrModelDesc')}
          />
        </div>
      </div>
    </SheetShell>
  )
}

function ModelContextRow({
  model,
  checked,
  onToggle,
  contextDraft,
  onContextDraft,
  onContextCommit,
  test,
  trailing
}: {
  model: { id: string; contextWindow?: number }
  checked: boolean
  onToggle: () => void
  contextDraft?: string
  onContextDraft: (value: string) => void
  onContextCommit: () => void
  test?: { status: 'testing' | 'passed' | 'failed'; message?: string }
  trailing?: ReactNode
}): ReactElement {
  const { t } = useTranslation('settings')
  return (
    <li className={`ds-llm-model-row ${checked ? 'is-on' : ''}`}>
      <button
        type="button"
        onClick={onToggle}
        title={test?.message || undefined}
        className="ds-llm-model-row__main"
      >
        <span
          className={`ds-llm-model-row__dot${
            test?.status === 'passed'
              ? ' is-passed'
              : test?.status === 'failed'
                ? ' is-failed'
                : test?.status === 'testing'
                  ? ' is-testing'
                  : ''
          }`}
          aria-hidden
        />
        <span className="ds-llm-model-row__name">{model.id}</span>
        {checked ? (
          <Check className="ds-llm-model-row__check h-4 w-4" strokeWidth={2.6} aria-hidden />
        ) : null}
      </button>
      <label className="ds-llm-model-row__ctx" title={t('modelContextWindowHint')}>
        <span className="ds-llm-model-row__ctx-label">{t('modelContextWindowLabel')}</span>
        <input
          type="text"
          inputMode="numeric"
          className="ds-llm-model-row__ctx-input"
          value={
            contextDraft ??
            String(model.contextWindow ?? CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT)
          }
          onChange={(e) => onContextDraft(e.target.value)}
          onBlur={onContextCommit}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </label>
      {trailing ? <div className="ds-llm-model-row__actions">{trailing}</div> : null}
    </li>
  )
}

function BuiltinProviderDetailSheet({
  providerId,
  config,
  onClose,
  onSave
}: {
  providerId: BuiltinLlmProviderId
  config: LlmProviderConfigV1
  onClose: () => void
  onSave: (next: LlmProviderConfigV1) => void
}): ReactElement | null {
  const { t } = useTranslation('settings')
  const def = BUILTIN_LLM_PROVIDERS[providerId]
  const [apiKey, setApiKey] = useState(config.apiKey)
  const [showKey, setShowKey] = useState(false)
  const [models, setModels] = useState<LlmProviderModelV1[]>(() =>
    config.models.length
      ? config.models
      : []
  )
  const [availableIds, setAvailableIds] = useState<string[]>(() => {
    const base = config.lastFetchedModels?.length
      ? config.lastFetchedModels
      : [...def.fallbackModels]
    const extras = config.models.map((m) => m.id).filter((id) => id && !base.includes(id))
    return [...base, ...extras]
  })
  const [modelDraft, setModelDraft] = useState('')
  const [fetchNote, setFetchNote] = useState<string | null>(null)
  const [fetching, setFetching] = useState(false)
  const [testingAll, setTestingAll] = useState(false)
  const [testByModel, setTestByModel] = useState<
    Record<string, { status: 'testing' | 'passed' | 'failed'; message?: string }>
  >({})
  const [lastFetchedModels, setLastFetchedModels] = useState<string[] | undefined>(
    config.lastFetchedModels
  )

  const modelMap = useMemo(() => {
    const map = new Map(models.map((model) => [model.id, model]))
    return map
  }, [models])

  const mergeAvailable = useCallback((primary: string[], keep: string[]): string[] => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const id of [...primary, ...keep]) {
      const trimmed = id.trim()
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      out.push(trimmed)
    }
    return out
  }, [])

  const ensureModel = (id: string, enabled = true): void => {
    setModels((prev) => {
      if (prev.some((model) => model.id === id)) {
        return prev.map((model) => (model.id === id ? { ...model, enabled } : model))
      }
      return [
        ...prev,
        {
          id,
          enabled,
          contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
        }
      ]
    })
  }

  const refreshModels = useCallback(
    async (key: string): Promise<void> => {
      const trimmed = key.trim()
      if (!trimmed) {
        setAvailableIds((prev) => mergeAvailable([...def.fallbackModels], prev))
        setFetchNote(t('llmModelsNeedKey'))
        return
      }
      setFetching(true)
      setFetchNote(null)
      try {
        await window.dsGui.setSettings({
          llmProviders: { [providerId]: { apiKey: trimmed } },
          ...(providerId === 'deepseek' ? { deepseek: { apiKey: trimmed } } : {})
        })
        const result = await window.dsGui.fetchProviderModels(providerId)
        if (result.ok) {
          setLastFetchedModels(result.modelIds)
          setFetchNote(null)
          setAvailableIds((prev) => mergeAvailable(result.modelIds, prev))
          setModels((prev) => {
            if (prev.length > 0) return prev
            const preferred = def.fallbackModels.filter((id) => result.modelIds.includes(id))
            const seed = preferred.length > 0 ? preferred : result.modelIds.slice(0, 2)
            return seed.map((id) => ({
              id,
              enabled: true,
              contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
            }))
          })
        } else {
          const fallback = result.fallbackModelIds?.length
            ? result.fallbackModelIds
            : [...def.fallbackModels]
          setAvailableIds((prev) => mergeAvailable(fallback, prev))
          setFetchNote(t('llmModelsFetchFailed'))
          setModels((prev) =>
            prev.length > 0
              ? prev
              : fallback.slice(0, 2).map((id) => ({
                  id,
                  enabled: true,
                  contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
                }))
          )
        }
      } catch (error) {
        setAvailableIds((prev) => mergeAvailable([...def.fallbackModels], prev))
        setFetchNote(error instanceof Error ? error.message : t('llmModelsFetchFailed'))
      } finally {
        setFetching(false)
      }
    },
    [def.fallbackModels, mergeAvailable, providerId, t]
  )

  useEffect(() => {
    if (apiKey.trim()) void refreshModels(apiKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const enabledCount = models.filter((model) => model.enabled).length

  const testSelectedModels = async (): Promise<void> => {
    const key = apiKey.trim()
    const ids = models.filter((model) => model.enabled).map((model) => model.id)
    if (!key || ids.length === 0 || testingAll) return
    setTestingAll(true)
    for (const modelId of ids) {
      setTestByModel((prev) => ({ ...prev, [modelId]: { status: 'testing' } }))
      try {
        const result = await window.dsGui.testEndpoint('openai', def.baseUrl, key, modelId)
        setTestByModel((prev) => ({
          ...prev,
          [modelId]: {
            status: result.ok ? 'passed' : 'failed',
            message: result.message
          }
        }))
      } catch (error) {
        setTestByModel((prev) => ({
          ...prev,
          [modelId]: {
            status: 'failed',
            message: error instanceof Error ? error.message : String(error)
          }
        }))
      }
    }
    setTestingAll(false)
  }

  const addManualModel = (): void => {
    const id = modelDraft.trim()
    if (!id) return
    setAvailableIds((prev) => (prev.includes(id) ? prev : [...prev, id]))
    ensureModel(id, true)
    setModelDraft('')
  }

  return (
    <SheetShell
      title={t(PROVIDER_NAME_KEY[providerId])}
      caption={t('llmProvidersHint')}
      icon={<ProviderBrandIcon id={providerId} size={40} />}
      onClose={onClose}
      footer={
        <>
          {config.apiKey.trim() ? (
            <button
              type="button"
              onClick={() =>
                onSave({
                  apiKey: '',
                  models: [],
                  lastFetchedModels: []
                })
              }
              className="ds-llm-sheet__btn ds-llm-sheet__btn--danger"
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              {t('llmClearProviderBtn')}
            </button>
          ) : null}
          <button type="button" onClick={onClose} className="ds-llm-sheet__btn">
            {t('llmProviderCancel')}
          </button>
          <button
            type="button"
            onClick={() => {
              const key = apiKey.trim()
              const nextModels =
                key && models.length === 0
                  ? def.fallbackModels.map((id) => ({
                      id,
                      enabled: true,
                      contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
                    }))
                  : key
                    ? models
                    : []
              onSave({
                apiKey: key,
                models: nextModels,
                lastFetchedModels: key && lastFetchedModels?.length ? lastFetchedModels : []
              })
            }}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--primary"
          >
            {t('saveEndpointBtn')}
          </button>
        </>
      }
    >
      <div className="ds-llm-inset">
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('llmBaseUrlLocked')}</div>
          <div className="ds-llm-inset__value" title={def.baseUrl}>
            {def.baseUrl}
          </div>
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('llmApiKey')}</div>
          <div className="ds-llm-inset__secret">
            <input
              type={showKey ? 'text' : 'password'}
              autoComplete="off"
              placeholder="sk-…"
              className="ds-llm-inset__input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              aria-label={showKey ? t('hideSecret') : t('showSecret')}
              onClick={() => setShowKey((v) => !v)}
              className="ds-llm-inset__eye"
            >
              {showKey ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
            </button>
          </div>
        </div>
      </div>

      <div className="ds-llm-sheet__section-label">
        <span>{t('llmAvailableModels')}</span>
        <span className="ds-llm-sheet__section-actions">
          <button
            type="button"
            disabled={!apiKey.trim() || enabledCount === 0 || testingAll}
            onClick={() => void testSelectedModels()}
            className="ds-llm-sheet__refresh"
          >
            {testingAll ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
            ) : (
              <Zap className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
            {t('llmTestSelectedModels')}
          </button>
          <button
            type="button"
            disabled={!apiKey.trim() || fetching}
            onClick={() => void refreshModels(apiKey)}
            className="ds-llm-sheet__refresh"
          >
            {fetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
            {t('llmRefreshModels')}
          </button>
        </span>
      </div>
      {fetchNote ? <p className="ds-llm-sheet__note">{fetchNote}</p> : null}

      <ul className="ds-llm-inset ds-llm-inset--list">
        {availableIds.map((modelId, index) => {
          const entry = modelMap.get(modelId)
          const checked = Boolean(entry?.enabled)
          const last = index === availableIds.length - 1
          const test = testByModel[modelId]
          return (
            <li key={modelId}>
              <button
                type="button"
                onClick={() => {
                  if (entry) {
                    setModels((prev) =>
                      prev.map((model) =>
                        model.id === modelId ? { ...model, enabled: !model.enabled } : model
                      )
                    )
                  } else {
                    ensureModel(modelId, true)
                  }
                }}
                title={test?.message || undefined}
                className={`ds-llm-inset__pick ${checked ? 'is-on' : ''} ${last ? 'is-last' : ''}`}
              >
                <span className="ds-llm-inset__pick-label">{modelId}</span>
                <span className="ds-llm-inset__pick-trailing">
                  {test?.status === 'testing' ? (
                    <Loader2
                      className="ds-llm-inset__pick-test is-testing h-4 w-4 animate-spin"
                      strokeWidth={2.2}
                    />
                  ) : test?.status === 'passed' ? (
                    <Check
                      className="ds-llm-inset__pick-test is-passed h-4 w-4"
                      strokeWidth={2.6}
                    />
                  ) : test?.status === 'failed' ? (
                    <X className="ds-llm-inset__pick-test is-failed h-4 w-4" strokeWidth={2.6} />
                  ) : null}
                  {checked ? (
                    <Check className="ds-llm-inset__pick-check h-4 w-4" strokeWidth={2.4} />
                  ) : null}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="ds-llm-sheet__add-model">
        <input
          type="text"
          autoComplete="off"
          placeholder={t('llmAddModelPlaceholder')}
          className="ds-llm-sheet__add-model-input"
          value={modelDraft}
          onChange={(e) => setModelDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              addManualModel()
            }
          }}
        />
        <button
          type="button"
          disabled={!modelDraft.trim()}
          onClick={addManualModel}
          className="ds-llm-sheet__add-model-btn"
        >
          {t('llmAddModelBtn')}
        </button>
      </div>
    </SheetShell>
  )
}

function CustomProviderDetailSheet({
  endpoint,
  onClose,
  onPatch,
  onSave,
  onDelete
}: {
  endpoint: CustomEndpointV1 | null
  onClose: () => void
  onPatch: (next: CustomEndpointV1) => void
  onSave: (next: CustomEndpointV1) => void
  onDelete: (id: string) => void
}): ReactElement | null {
  const { t } = useTranslation('settings')
  const [name, setName] = useState(endpoint?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(endpoint?.baseUrl ?? '')
  const [apiKey, setApiKey] = useState(endpoint?.apiKey ?? '')
  const [protocol, setProtocol] = useState<EndpointProtocol>(endpoint?.protocol ?? 'openai')
  const [showKey, setShowKey] = useState(false)
  const [models, setModels] = useState(endpoint?.models ?? [])
  const [modelDraft, setModelDraft] = useState('')
  const [contextDraft, setContextDraft] = useState(String(CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT))
  const [contextDrafts, setContextDrafts] = useState<Record<string, string>>({})
  const [testingAll, setTestingAll] = useState(false)
  const [testByModel, setTestByModel] = useState<
    Record<string, { status: 'testing' | 'passed' | 'failed'; message?: string }>
  >({})

  if (!endpoint) return null

  const draftEndpoint = (nextModels = models): CustomEndpointV1 => ({
    ...endpoint,
    name: name.trim() || endpoint.name,
    baseUrl: baseUrl.trim() || endpoint.baseUrl,
    apiKey: apiKey.trim() || endpoint.apiKey,
    protocol,
    enabled: true,
    models: nextModels
  })

  const commitModels = (nextModels: CustomEndpointV1['models']): void => {
    setModels(nextModels)
    onPatch(draftEndpoint(nextModels))
  }

  const addModel = (): void => {
    const id = modelDraft.trim()
    if (!id || models.some((model) => model.id === id)) return
    commitModels([
      ...models,
      {
        id,
        enabled: true,
        contextWindow: normalizeCustomModelContextWindow(contextDraft),
        testStatus: 'untested'
      }
    ])
    setModelDraft('')
    setContextDraft(String(CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT))
  }

  const testSelected = async (): Promise<void> => {
    const ids = models.filter((model) => model.enabled).map((model) => model.id)
    if (!apiKey.trim() || !baseUrl.trim() || ids.length === 0 || testingAll) return
    setTestingAll(true)
    let working = models
    for (const modelId of ids) {
      setTestByModel((prev) => ({ ...prev, [modelId]: { status: 'testing' } }))
      try {
        const result = await window.dsGui.testEndpoint(protocol, baseUrl.trim(), apiKey.trim(), modelId)
        setTestByModel((prev) => ({
          ...prev,
          [modelId]: { status: result.ok ? 'passed' : 'failed', message: result.message }
        }))
        working = working.map((model) =>
          model.id === modelId
            ? {
                ...model,
                testStatus: result.ok ? ('passed' as const) : ('failed' as const),
                toolCalling: result.ok,
                lastTestedAt: new Date().toISOString()
              }
            : model
        )
        commitModels(working)
      } catch (error) {
        setTestByModel((prev) => ({
          ...prev,
          [modelId]: {
            status: 'failed',
            message: error instanceof Error ? error.message : String(error)
          }
        }))
      }
    }
    setTestingAll(false)
  }

  return (
    <SheetShell
      title={name || endpoint.name}
      icon={<BrandIcon token="openai" size={40} />}
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={() => onDelete(endpoint.id)}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--danger"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
            {t('deleteEndpointBtn')}
          </button>
          <button type="button" onClick={onClose} className="ds-llm-sheet__btn">
            {t('llmProviderCancel')}
          </button>
          <button
            type="button"
            disabled={!name.trim() || !baseUrl.trim() || !apiKey.trim()}
            onClick={() => onSave(draftEndpoint())}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--primary"
          >
            {t('saveEndpointBtn')}
          </button>
        </>
      }
    >
      <div className="ds-llm-inset">
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointNameLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointUrlLabel')}</div>
          <input
            className="ds-llm-inset__input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('llmApiKey')}</div>
          <div className="ds-llm-inset__secret">
            <input
              type={showKey ? 'text' : 'password'}
              autoComplete="off"
              placeholder="sk-…"
              className="ds-llm-inset__input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              aria-label={showKey ? t('hideSecret') : t('showSecret')}
              className="ds-llm-inset__eye"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
            </button>
          </div>
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('endpointProtocolLabel')}</div>
          <select
            className="ds-llm-inset__input"
            value={protocol}
            onChange={(e) => setProtocol(e.target.value as EndpointProtocol)}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
      </div>

      <div className="ds-llm-sheet__section-label">
        <span>{t('llmAvailableModels')}</span>
        <span className="ds-llm-sheet__section-actions">
          <button
            type="button"
            disabled={!apiKey.trim() || models.filter((m) => m.enabled).length === 0 || testingAll}
            onClick={() => void testSelected()}
            className="ds-llm-sheet__refresh"
          >
            {testingAll ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
            ) : (
              <Zap className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
            {t('llmTestSelectedModels')}
          </button>
        </span>
      </div>

      <ul className="ds-llm-inset ds-llm-inset--list">
        {models.map((model) => (
          <ModelContextRow
            key={model.id}
            model={model}
            checked={model.enabled}
            onToggle={() =>
              commitModels(
                models.map((item) =>
                  item.id === model.id ? { ...item, enabled: !item.enabled } : item
                )
              )
            }
            contextDraft={contextDrafts[model.id]}
            onContextDraft={(value) =>
              setContextDrafts((prev) => ({ ...prev, [model.id]: value }))
            }
            onContextCommit={() => {
              const draft = contextDrafts[model.id]
              if (draft === undefined) return
              const next = normalizeCustomModelContextWindow(draft)
              setContextDrafts((prev) => {
                const rest = { ...prev }
                delete rest[model.id]
                return rest
              })
              commitModels(
                models.map((item) =>
                  item.id === model.id ? { ...item, contextWindow: next } : item
                )
              )
            }}
            test={testByModel[model.id]}
            trailing={
              <button
                type="button"
                className="ds-llm-model-row__remove"
                onClick={() => {
                  void window.dsGui
                    .pruneUsageEndpointModel(endpoint.id, model.id)
                    .finally(() => {
                      useChatStore.setState((state) => ({
                        usageRefreshKey: state.usageRefreshKey + 1
                      }))
                    })
                  commitModels(models.filter((item) => item.id !== model.id))
                }}
                aria-label={t('deleteEndpointBtn')}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            }
          />
        ))}
      </ul>

      <div className="ds-llm-sheet__add-model ds-llm-sheet__add-model--inset">
        <input
          type="text"
          className="ds-llm-sheet__add-model-input"
          placeholder={t('llmAddModelPlaceholder')}
          value={modelDraft}
          onChange={(e) => setModelDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.nativeEvent.isComposing || e.keyCode === 229) return
            e.preventDefault()
            addModel()
          }}
        />
        <input
          type="text"
          inputMode="numeric"
          className="ds-llm-sheet__add-model-input ds-llm-sheet__add-model-input--ctx"
          placeholder={t('modelContextWindowLabel')}
          value={contextDraft}
          onChange={(e) => setContextDraft(e.target.value)}
          title={t('modelContextWindowHint')}
        />
        <button
          type="button"
          disabled={!modelDraft.trim()}
          onClick={addModel}
          className="ds-llm-sheet__add-model-btn"
        >
          {t('llmAddModelBtn')}
        </button>
      </div>
    </SheetShell>
  )
}

function AsrProviderDetailSheet({
  provider,
  onClose,
  onPatch,
  onSave,
  onDelete
}: {
  provider: AsrProviderV1 | null
  onClose: () => void
  onPatch: (next: AsrProviderV1) => void
  onSave: (next: AsrProviderV1) => void
  onDelete?: (id: string) => void
}): ReactElement | null {
  const { t } = useTranslation('settings')
  const [name, setName] = useState(provider?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(provider?.baseUrl || DEFAULT_ASR_BASE_URL)
  const [apiKey, setApiKey] = useState(provider?.apiKey ?? '')
  const [showKey, setShowKey] = useState(false)
  const [models, setModels] = useState(provider?.models ?? [])
  const [modelDraft, setModelDraft] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    status: 'passed' | 'failed'
    message: string
  } | null>(null)

  if (!provider) return null
  const builtin = Boolean(provider.builtin || provider.id === BUILTIN_ASR_PROVIDER_ID)
  const activeModel =
    models.find((model) => model.enabled)?.id || models[0]?.id || DEFAULT_ASR_MODEL

  const draftProvider = (nextModels = models): AsrProviderV1 => ({
    ...provider,
    name: builtin ? provider.name : name.trim() || provider.name,
    baseUrl: baseUrl.trim() || DEFAULT_ASR_BASE_URL,
    apiKey: apiKey.trim(),
    models: nextModels
  })

  const commitModels = (nextModels: AsrProviderV1['models']): void => {
    setModels(nextModels)
    onPatch(draftProvider(nextModels))
  }

  const runAsrTest = async (): Promise<void> => {
    const key = apiKey.trim()
    const modelId = activeModel.trim() || DEFAULT_ASR_MODEL
    const url = baseUrl.trim() || DEFAULT_ASR_BASE_URL
    if (!key || testing) return
    setTesting(true)
    setTestResult(null)
    try {
      if (typeof window.dsGui.testAsrEndpoint === 'function') {
        const result = await window.dsGui.testAsrEndpoint({
          apiKey: key,
          model: modelId,
          baseUrl: url
        })
        setTestResult({
          status: result.ok ? 'passed' : 'failed',
          message: result.message
        })
        return
      }
      await window.dsGui.setAsrConfig({
        apiKey: key,
        model: modelId,
        baseUrl: url
      })
      const wav = buildSilentWavProbeBytes()
      const audio = new ArrayBuffer(wav.byteLength)
      new Uint8Array(audio).set(wav)
      const result = await window.dsGui.transcribeAudio({
        audio,
        mimeType: 'audio/wav',
        fileName: 'asr-probe.wav'
      })
      if (result.ok || result.message === 'No speech detected in the recording.') {
        setTestResult({
          status: 'passed',
          message: result.ok ? 'ASR ok' : 'ASR endpoint accepted the probe'
        })
      } else {
        setTestResult({ status: 'failed', message: result.message })
      }
    } catch (error) {
      setTestResult({
        status: 'failed',
        message: error instanceof Error ? error.message : String(error)
      })
    } finally {
      setTesting(false)
    }
  }

  const addAsrModel = (): void => {
    const id = modelDraft.trim()
    if (!id || models.some((model) => model.id === id)) return
    commitModels([...models, { id, enabled: true }])
    setModelDraft('')
  }

  return (
    <SheetShell
      title={builtin ? t('asrProviderZhipu') : name || provider.name}
      caption={t('asrProviderHint')}
      icon={<BrandIcon token="glm" size={40} />}
      onClose={onClose}
      footer={
        <>
          {builtin && provider.apiKey.trim() ? (
            <button
              type="button"
              onClick={() => onSave({ ...draftProvider(), apiKey: '' })}
              className="ds-llm-sheet__btn ds-llm-sheet__btn--danger"
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              {t('llmClearProviderBtn')}
            </button>
          ) : onDelete ? (
            <button
              type="button"
              onClick={() => onDelete(provider.id)}
              className="ds-llm-sheet__btn ds-llm-sheet__btn--danger"
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
              {t('deleteEndpointBtn')}
            </button>
          ) : null}
          <button type="button" onClick={onClose} className="ds-llm-sheet__btn">
            {t('llmProviderCancel')}
          </button>
          <button
            type="button"
            onClick={() => onSave(draftProvider())}
            className="ds-llm-sheet__btn ds-llm-sheet__btn--primary"
          >
            {t('saveEndpointBtn')}
          </button>
        </>
      }
    >
      <div className="ds-llm-inset">
        {builtin ? null : (
          <div className="ds-llm-inset__row">
            <div className="ds-llm-inset__key">{t('endpointNameLabel')}</div>
            <input
              className="ds-llm-inset__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        )}
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('asrBaseUrl')}</div>
          <input
            className="ds-llm-inset__input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={DEFAULT_ASR_BASE_URL}
          />
        </div>
        <div className="ds-llm-inset__row">
          <div className="ds-llm-inset__key">{t('asrApiKey')}</div>
          <div className="ds-llm-inset__secret">
            <input
              type={showKey ? 'text' : 'password'}
              autoComplete="off"
              placeholder="sk-…"
              className="ds-llm-inset__input"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              aria-label={showKey ? t('hideSecret') : t('showSecret')}
              className="ds-llm-inset__eye"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
            </button>
          </div>
        </div>
      </div>

      <div className="ds-llm-sheet__section-label">
        <span>{t('llmAvailableModels')}</span>
        <span className="ds-llm-sheet__section-actions">
          <button
            type="button"
            disabled={!apiKey.trim() || testing}
            onClick={() => void runAsrTest()}
            className="ds-llm-sheet__refresh"
          >
            {testing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
            ) : (
              <Zap className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
            {t('asrTestBtn')}
          </button>
        </span>
      </div>
      {testResult ? (
        <p
          className={`ds-llm-sheet__note ${
            testResult.status === 'passed'
              ? 'ds-llm-sheet__note--ok'
              : 'ds-llm-sheet__note--err'
          }`}
        >
          {testResult.message}
        </p>
      ) : builtin ? (
        <p className="ds-llm-sheet__note">{t('asrShareKeyHint')}</p>
      ) : null}

      <ul className="ds-llm-inset ds-llm-inset--list">
        {models.map((model, index) => {
          const last = index === models.length - 1
          return (
            <li key={model.id}>
              <button
                type="button"
                onClick={() =>
                  commitModels(
                    models.map((item) =>
                      item.id === model.id ? { ...item, enabled: !item.enabled } : item
                    )
                  )
                }
                className={`ds-llm-inset__pick ${model.enabled ? 'is-on' : ''} ${
                  last ? 'is-last' : ''
                }`}
              >
                <span className="ds-llm-inset__pick-label">{model.id}</span>
                {model.enabled ? (
                  <Check className="ds-llm-inset__pick-check h-4 w-4" strokeWidth={2.4} />
                ) : null}
              </button>
            </li>
          )
        })}
      </ul>

      <div className="ds-llm-sheet__add-model">
        <input
          type="text"
          className="ds-llm-sheet__add-model-input"
          placeholder={t('llmAddModelPlaceholder')}
          value={modelDraft}
          onChange={(e) => setModelDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || e.nativeEvent.isComposing || e.keyCode === 229) return
            e.preventDefault()
            addAsrModel()
          }}
        />
        <button
          type="button"
          disabled={!modelDraft.trim()}
          onClick={addAsrModel}
          className="ds-llm-sheet__add-model-btn"
        >
          {t('llmAddModelBtn')}
        </button>
      </div>
    </SheetShell>
  )
}
