import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save, Send } from 'lucide-react'
import { isWecomWebhookConfigured, parseWecomWebhookKey } from '@shared/wecom-channel'
import { loadWecomChannelState, saveWecomWebhookKey } from '../../lib/resolve-automation-wecom-config'
import { FieldHelpPopover } from './FieldHelpPopover'

type Props = {
  runtimeReady: boolean
  onConfigured: () => void
}

type Notice = { tone: 'success' | 'error' | 'info'; message: string }

export function WecomChannelSetup({ runtimeReady, onConfigured }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [webhookInput, setWebhookInput] = useState('')
  const [configured, setConfigured] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const webhookHelpSteps = t('channelWecomWebhookHelpSteps').split('\n').filter(Boolean)

  const loadState = useCallback(async () => {
    try {
      const result = await loadWecomChannelState()
      setConfigured(result.configured)
      if (result.configured) {
        setWebhookInput('••••••••-••••-••••-••••-••••••••••••')
      } else {
        setWebhookInput('')
      }
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

  const handleSave = async (): Promise<void> => {
    const key = parseWecomWebhookKey(webhookInput)
    if (!key) {
      setNotice({ tone: 'error', message: t('channelWecomInvalidWebhook') })
      return
    }
    setSaving(true)
    setNotice(null)
    try {
      await saveWecomWebhookKey(key)
      setConfigured(true)
      setWebhookInput('••••••••-••••-••••-••••-••••••••••••')
      onConfigured()
      setNotice({ tone: 'success', message: t('channelWecomSaved') })
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
    if (!configured && !isWecomWebhookConfigured(webhookInput)) {
      setNotice({ tone: 'error', message: t('channelWecomSaveBeforeTest') })
      return
    }
    if (!runtimeReady) {
      setNotice({ tone: 'info', message: t('channelWecomNeedRuntime') })
      return
    }
    setTesting(true)
    setNotice(null)
    try {
      const raw = await window.dsGui.runtimeRequest(
        '/v1/automation/wecom/test-send',
        'POST',
        JSON.stringify({ text: t('channelWecomTestMessage') })
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
      setNotice({ tone: 'success', message: t('channelWecomTestOk') })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setTesting(false)
    }
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

      <p className="text-[13px] leading-6 text-ds-muted">{t('channelWecomSimpleDesc')}</p>

      <label className="grid gap-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-medium text-ds-ink">{t('channelWecomWebhook')}</span>
          <FieldHelpPopover
            title={t('channelWecomWebhookHelpTitle')}
            intro={t('channelWecomWebhookHelpIntro')}
            steps={webhookHelpSteps}
            ariaLabel={t('channelWecomWebhookHelpTitle')}
          />
        </div>
        <input
          value={webhookInput}
          onChange={(event) => {
            setConfigured(false)
            setWebhookInput(event.target.value)
          }}
          placeholder={t('channelWecomWebhookPlaceholder')}
          className="rounded-lg border border-ds-border bg-ds-main px-3 py-2 font-mono text-[12px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60"
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-ds-ink px-4 py-2 text-[13px] font-medium text-ds-card hover:opacity-80 disabled:opacity-50"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {t('channelWecomSave')}
        </button>
        <button
          type="button"
          onClick={() => void handleTestSend()}
          disabled={testing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border px-4 py-2 text-[13px] font-medium text-ds-ink hover:bg-ds-subtle disabled:opacity-50"
        >
          {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          {t('channelWecomTestSend')}
        </button>
      </div>
    </div>
  )
}
