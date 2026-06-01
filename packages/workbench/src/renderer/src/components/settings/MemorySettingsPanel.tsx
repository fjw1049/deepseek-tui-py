import type { ReactElement, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type {
  AppSettingsV1,
  MemoryEmbeddingProvider,
  MemoryFtsTokenizer,
  MemoryMode,
  MemorySettingsPatchV1
} from '@shared/app-settings'
import { defaultMemorySettings, mergeMemorySettings } from '@shared/app-settings'
import { Database, Search, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react'
import { SettingsSelect } from './SettingsSelect'

type Props = {
  form: AppSettingsV1
  configPath: string
  onMemoryPatch: (patch: MemorySettingsPatchV1) => void
}

function Toggle({
  checked,
  onChange
}: {
  checked: boolean
  onChange: (v: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition ${
        checked ? 'bg-emerald-500' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-[22px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

function Card({
  title,
  icon,
  children
}: {
  title: string
  icon: ReactNode
  children: ReactNode
}): ReactElement {
  return (
    <section className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm shadow-black/5 dark:shadow-black/25">
      <div className="flex items-center gap-2 border-b border-ds-border-muted px-5 py-3">
        <span className="text-accent">{icon}</span>
        <h2 className="text-[16px] font-semibold text-ds-ink">{title}</h2>
      </div>
      <div className="divide-y divide-ds-border-muted px-2 py-1">{children}</div>
    </section>
  )
}

function Row({
  title,
  description,
  control,
  wide = false
}: {
  title: string
  description?: ReactNode
  control: ReactNode
  wide?: boolean
}): ReactElement {
  return (
    <div
      className={`flex gap-3 px-3 py-4 ${
        wide ? 'flex-col sm:gap-3.5' : 'flex-col sm:flex-row sm:items-start sm:justify-between sm:gap-8'
      }`}
    >
      <div className={`min-w-0 ${wide ? 'w-full max-w-none shrink-0' : 'flex-1'}`}>
        <div className="text-[14px] font-semibold text-ds-ink">{title}</div>
        {typeof description === 'string' ? (
          <p className="mt-0.5 text-[13px] leading-relaxed text-ds-muted">{description}</p>
        ) : description ? (
          <div className="mt-0.5 text-[13px] leading-relaxed text-ds-muted">{description}</div>
        ) : null}
      </div>
      <div className={`w-full min-w-0 sm:ml-auto sm:shrink-0 ${wide ? '' : 'sm:max-w-[210px]'}`}>
        {wide ? control : <div className="flex w-full justify-end">{control}</div>}
      </div>
    </div>
  )
}

function NumberInput({
  value,
  min,
  max,
  step = 1,
  onChange
}: {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
}): ReactElement {
  return (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-32 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
    />
  )
}

const textInputClass =
  'w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30'

export function MemorySettingsPanel({
  form,
  configPath,
  onMemoryPatch
}: Props): ReactElement {
  const { t } = useTranslation('settings')
  const memory = mergeMemorySettings(form.memory ?? defaultMemorySettings(), undefined)
  const smart = memory.smart
  const smartActive = memory.enabled && smart.enabled && memory.mode !== 'manual'
  const embeddingActive = smart.embeddingProvider !== 'none'

  return (
    <div className="flex flex-col gap-6">
      <Card title={t('memoryStatusTitle')} icon={<ShieldCheck className="h-4 w-4" />}>
        <Row
          title={t('memoryEnabled')}
          description={t('memoryEnabledDesc')}
          control={<Toggle checked={memory.enabled} onChange={(enabled) => onMemoryPatch({ enabled })} />}
        />
        <Row
          title={t('memoryMode')}
          description={t('memoryModeDesc')}
          control={
            <SettingsSelect
              value={memory.mode}
              onChange={(event) => onMemoryPatch({ mode: event.target.value as MemoryMode })}
            >
              <option value="manual">{t('memoryModeManual')}</option>
              <option value="hybrid">{t('memoryModeHybrid')}</option>
              <option value="auto">{t('memoryModeAuto')}</option>
            </SettingsSelect>
          }
        />
        <Row
          title={t('memorySmartEnabled')}
          description={t('memorySmartEnabledDesc')}
          control={
            <Toggle
              checked={smart.enabled}
              onChange={(enabled) => onMemoryPatch({ smart: { enabled } })}
            />
          }
        />
        <Row
          title={t('memoryConfigPath')}
          description={t('memoryConfigPathDesc')}
          wide
          control={
            <code className="block w-full break-all rounded-xl bg-ds-main/70 px-3 py-2 font-mono text-[12px] text-ds-muted shadow-sm">
              {configPath}
            </code>
          }
        />
      </Card>

      <Card title={t('memoryRecallTitle')} icon={<Search className="h-4 w-4" />}>
        <Row
          title={t('memoryRecallEnabled')}
          description={t('memoryRecallEnabledDesc')}
          control={
            <Toggle
              checked={smart.recallEnabled}
              onChange={(recallEnabled) => onMemoryPatch({ smart: { recallEnabled } })}
            />
          }
        />
        <Row
          title={t('memoryRecallLimit')}
          description={t('memoryRecallLimitDesc')}
          control={
            <NumberInput
              value={smart.recallLimit}
              min={1}
              max={20}
              onChange={(recallLimit) => onMemoryPatch({ smart: { recallLimit } })}
            />
          }
        />
        <Row
          title={t('memoryRecallStrictness')}
          description={t('memoryRecallStrictnessDesc')}
          control={
            <SettingsSelect
              value={String(smart.recallScoreThreshold)}
              onChange={(event) =>
                onMemoryPatch({ smart: { recallScoreThreshold: Number(event.target.value) } })
              }
            >
              <option value="0.15">{t('memoryStrictnessLoose')}</option>
              <option value="0.3">{t('memoryStrictnessBalanced')}</option>
              <option value="0.5">{t('memoryStrictnessStrict')}</option>
            </SettingsSelect>
          }
        />
        <Row
          title={t('memoryRecallTimeout')}
          description={t('memoryRecallTimeoutDesc')}
          control={
            <NumberInput
              value={smart.recallTimeoutMs}
              min={250}
              max={30000}
              step={250}
              onChange={(recallTimeoutMs) => onMemoryPatch({ smart: { recallTimeoutMs } })}
            />
          }
        />
      </Card>

      <Card title={t('memoryCaptureTitle')} icon={<Database className="h-4 w-4" />}>
        <Row
          title={t('memoryCaptureEnabled')}
          description={t('memoryCaptureEnabledDesc')}
          control={
            <Toggle
              checked={smart.captureEnabled}
              onChange={(captureEnabled) => onMemoryPatch({ smart: { captureEnabled } })}
            />
          }
        />
        <Row
          title={t('memoryCaptureMinChars')}
          description={t('memoryCaptureMinCharsDesc')}
          control={
            <NumberInput
              value={smart.captureMinUserChars}
              min={0}
              max={500}
              onChange={(captureMinUserChars) => onMemoryPatch({ smart: { captureMinUserChars } })}
            />
          }
        />
        <Row
          title={t('memoryExtractionFrequency')}
          description={t('memoryExtractionFrequencyDesc')}
          control={
            <NumberInput
              value={smart.l1EveryN}
              min={1}
              max={100}
              onChange={(l1EveryN) => onMemoryPatch({ smart: { l1EveryN } })}
            />
          }
        />
        <Row
          title={t('memoryConfidence')}
          description={t('memoryConfidenceDesc')}
          control={
            <NumberInput
              value={smart.l1ConfidenceMin}
              min={0}
              max={1}
              step={0.05}
              onChange={(l1ConfidenceMin) => onMemoryPatch({ smart: { l1ConfidenceMin } })}
            />
          }
        />
        <Row
          title={t('memoryDecay')}
          description={t('memoryDecayDesc')}
          control={
            <NumberInput
              value={smart.l1DecayHalfLifeDays}
              min={0}
              max={3650}
              onChange={(l1DecayHalfLifeDays) => onMemoryPatch({ smart: { l1DecayHalfLifeDays } })}
            />
          }
        />
      </Card>

      <Card title={t('memoryDataTitle')} icon={<SlidersHorizontal className="h-4 w-4" />}>
        <Row
          title={t('memoryDataDir')}
          description={t('memoryDataDirDesc')}
          control={
            <input
              className={textInputClass}
              value={smart.dataDir}
              placeholder="~/.deepseek/memory_data"
              onChange={(event) => onMemoryPatch({ smart: { dataDir: event.target.value } })}
            />
          }
        />
        <Row
          title={t('memoryHybridSearch')}
          description={t('memoryHybridSearchDesc')}
          control={
            <Toggle
              checked={smart.hybridSearch}
              onChange={(hybridSearch) => onMemoryPatch({ smart: { hybridSearch } })}
            />
          }
        />
        <Row
          title={t('memoryFtsTokenizer')}
          description={t('memoryFtsTokenizerDesc')}
          control={
            <SettingsSelect
              value={smart.ftsTokenizer}
              onChange={(event) =>
                onMemoryPatch({ smart: { ftsTokenizer: event.target.value as MemoryFtsTokenizer } })
              }
            >
              <option value="auto">{t('memoryTokenizerAuto')}</option>
              <option value="simple">{t('memoryTokenizerSimple')}</option>
              <option value="jieba">{t('memoryTokenizerJieba')}</option>
            </SettingsSelect>
          }
        />
        <div className="px-3 py-3 text-[12px] leading-5 text-ds-faint">
          {smartActive ? t('memoryRuntimeRestartHint') : t('memoryInactiveHint')}
        </div>
      </Card>

      <Card title={t('memoryEmbeddingTitle')} icon={<Sparkles className="h-4 w-4" />}>
        <Row
          title={t('memoryEmbeddingProvider')}
          description={t('memoryEmbeddingProviderDesc')}
          control={
            <SettingsSelect
              value={smart.embeddingProvider}
              onChange={(event) =>
                onMemoryPatch({
                  smart: { embeddingProvider: event.target.value as MemoryEmbeddingProvider }
                })
              }
            >
              <option value="none">{t('memoryEmbeddingNone')}</option>
              <option value="openai">{t('memoryEmbeddingOpenAI')}</option>
            </SettingsSelect>
          }
        />
        <fieldset disabled={!embeddingActive} className={embeddingActive ? '' : 'opacity-45'}>
          <Row
            title={t('memoryEmbeddingModel')}
            description={t('memoryEmbeddingModelDesc')}
            control={
              <input
                className={textInputClass}
                value={smart.embeddingModel}
                onChange={(event) => onMemoryPatch({ smart: { embeddingModel: event.target.value } })}
              />
            }
          />
          <Row
            title={t('memoryEmbeddingBaseUrl')}
            description={t('memoryEmbeddingBaseUrlDesc')}
            control={
              <input
                className={textInputClass}
                value={smart.embeddingBaseUrl}
                placeholder="https://api.example.com"
                onChange={(event) =>
                  onMemoryPatch({ smart: { embeddingBaseUrl: event.target.value } })
                }
              />
            }
          />
          <Row
            title={t('memoryEmbeddingApiKey')}
            description={t('memoryEmbeddingApiKeyDesc')}
            control={
              <input
                type="password"
                className={textInputClass}
                value={smart.embeddingApiKey}
                onChange={(event) =>
                  onMemoryPatch({ smart: { embeddingApiKey: event.target.value } })
                }
              />
            }
          />
          <Row
            title={t('memoryEmbeddingBackfill')}
            description={t('memoryEmbeddingBackfillDesc')}
            control={
              <Toggle
                checked={smart.embeddingBackfillOnStart}
                onChange={(embeddingBackfillOnStart) =>
                  onMemoryPatch({ smart: { embeddingBackfillOnStart } })
                }
              />
            }
          />
        </fieldset>
      </Card>
    </div>
  )
}
