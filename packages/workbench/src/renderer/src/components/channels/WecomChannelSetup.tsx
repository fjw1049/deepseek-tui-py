import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save, Send } from 'lucide-react'
import { isWecomWebhookConfigured, parseWecomWebhookKey } from '@shared/wecom-channel'
import { loadWecomChannelState, saveWecomWebhookKey } from '../../lib/resolve-automation-wecom-config'
import { FieldHelpPopover } from './FieldHelpPopover'
import {
  CHANNEL_ACTIONS,
  CHANNEL_BTN_ICON,
  CHANNEL_CONTROL,
  CHANNEL_FIELD,
  CHANNEL_HINT,
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
      {notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}

      <p className={CHANNEL_HINT}>{t('channelWecomSimpleDesc')}</p>

      <label className={CHANNEL_FIELD}>
        <div className="flex items-center gap-1.5">
          <span className={CHANNEL_LABEL}>{t('channelWecomWebhook')}</span>
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
          className={`${CHANNEL_CONTROL} font-mono text-[12px]`}
        />
      </label>

      <div className={CHANNEL_ACTIONS}>
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className={CHANNEL_PRIMARY_BTN}
        >
          {saving ? (
            <Loader2 className={`${CHANNEL_BTN_ICON} animate-spin`} />
          ) : (
            <Save className={CHANNEL_BTN_ICON} />
          )}
          {t('channelWecomSave')}
        </button>
        <button
          type="button"
          onClick={() => void handleTestSend()}
          disabled={testing}
          className={CHANNEL_SECONDARY_BTN}
        >
          {testing ? (
            <Loader2 className={`${CHANNEL_BTN_ICON} animate-spin`} />
          ) : (
            <Send className={CHANNEL_BTN_ICON} />
          )}
          {t('channelWecomTestSend')}
        </button>
      </div>
    </div>
  )
}
