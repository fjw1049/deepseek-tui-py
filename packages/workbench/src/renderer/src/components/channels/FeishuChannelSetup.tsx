import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import QRCode from 'qrcode'
import { Loader2, QrCode, Send, XCircle } from 'lucide-react'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'
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

type ScanPhase = 'idle' | 'scanning' | 'success' | 'error'

export function FeishuChannelSetup({ runtimeReady, onConfigured }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [config, setConfig] = useState<FeishuConfigV1 | null>(null)
  const [target, setTarget] = useState<'feishu' | 'lark'>('feishu')
  const [phase, setPhase] = useState<ScanPhase>('idle')
  const [qrDataUrl, setQrDataUrl] = useState('')
  const [qrExpireIn, setQrExpireIn] = useState(0)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [testing, setTesting] = useState(false)

  const configured = Boolean(config?.appId?.trim() && config?.appSecret?.trim())

  const loadConfig = useCallback(async () => {
    try {
      const file = await window.dsGui.getFeishuConfig()
      setConfig(file.config)
      if (file.config.domain === 'lark') setTarget('lark')
    } catch (err) {
      setNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    }
  }, [])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (typeof window.dsGui.onFeishuRegisterEvent !== 'function') return undefined
    return window.dsGui.onFeishuRegisterEvent((event) => {
      if (event.type === 'qr') {
        setQrExpireIn(event.expireIn)
        void QRCode.toDataURL(event.url, { margin: 1, width: 220 }).then(setQrDataUrl)
      }
    })
  }, [])

  const saveAndNotify = async (next: FeishuConfigV1): Promise<void> => {
    await window.dsGui.setFeishuConfig(next)
    setConfig(next)
    onConfigured()
  }

  const runTestSend = async (receiveId: string): Promise<void> => {
    if (!runtimeReady) {
      setNotice({ tone: 'info', message: t('channelFeishuNeedRuntimeForTest') })
      return
    }
    setTesting(true)
    setNotice(null)
    try {
      const raw = await window.dsGui.runtimeRequest(
        '/v1/automation/feishu/test-send',
        'POST',
        JSON.stringify({
          receive_id: receiveId,
          text: t('channelFeishuTestMessage')
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
      setNotice({ tone: 'success', message: t('channelFeishuTestOk') })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setTesting(false)
    }
  }

  const startScan = async (): Promise<void> => {
    if (typeof window.dsGui.startFeishuRegister !== 'function') {
      setNotice({ tone: 'error', message: t('channelFeishuScanUnavailable') })
      return
    }
    setPhase('scanning')
    setNotice(null)
    setQrDataUrl('')
    try {
      const result = await window.dsGui.startFeishuRegister({ target })
      if (!result.ok) {
        setPhase('error')
        setNotice({ tone: 'error', message: result.message })
        return
      }
      const receiveId = config?.chatId?.trim() || result.result.openId?.trim() || ''
      const next: FeishuConfigV1 = {
        appId: result.result.appId,
        appSecret: result.result.appSecret,
        domain: result.result.domain,
        chatId: receiveId
      }
      await saveAndNotify(next)
      setPhase('success')
      setNotice({ tone: 'success', message: t('channelFeishuScanSuccess') })
      if (receiveId) {
        await runTestSend(receiveId)
      }
    } catch (err) {
      setPhase('error')
      setNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    }
  }

  const cancelScan = (): void => {
    void window.dsGui.cancelFeishuRegister?.()
    setPhase('idle')
    setQrDataUrl('')
  }

  return (
    <div className="flex flex-col gap-4">
      {notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}

      <p className={CHANNEL_HINT}>{t('channelFeishuSimpleDesc')}</p>

      <label className={CHANNEL_FIELD}>
        <span className={CHANNEL_LABEL}>{t('channelFeishuTarget')}</span>
        <select
          className={CHANNEL_CONTROL}
          value={target}
          disabled={phase === 'scanning'}
          onChange={(e) => setTarget(e.target.value as 'feishu' | 'lark')}
        >
          <option value="feishu">{t('channelFeishuTargetFeishu')}</option>
          <option value="lark">{t('channelFeishuTargetLark')}</option>
        </select>
      </label>

      <div className={CHANNEL_ACTIONS}>
        {phase === 'scanning' ? (
          <button type="button" onClick={cancelScan} className={CHANNEL_SECONDARY_BTN}>
            <XCircle className={CHANNEL_BTN_ICON} />
            {t('channelFeishuScanCancel')}
          </button>
        ) : (
          <button type="button" onClick={() => void startScan()} className={CHANNEL_PRIMARY_BTN}>
            <QrCode className={CHANNEL_BTN_ICON} />
            {configured ? t('channelFeishuScanReconnect') : t('channelFeishuScanConnect')}
          </button>
        )}
        {configured && config?.chatId?.trim() ? (
          <button
            type="button"
            disabled={!runtimeReady || testing}
            onClick={() => void runTestSend(config.chatId.trim())}
            className={CHANNEL_SECONDARY_BTN}
          >
            {testing ? (
              <Loader2 className={`${CHANNEL_BTN_ICON} animate-spin`} />
            ) : (
              <Send className={CHANNEL_BTN_ICON} />
            )}
            {t('channelFeishuTestSend')}
          </button>
        ) : null}
      </div>

      {phase === 'scanning' ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-ds-border-muted bg-ds-subtle/40 px-4 py-4">
          {qrDataUrl ? (
            <img
              src={qrDataUrl}
              alt={t('channelFeishuScanQrAlt')}
              className="rounded-lg border border-ds-border bg-white p-2"
            />
          ) : (
            <div className="flex items-center gap-2 py-8 text-[13px] text-ds-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('channelFeishuScanGenerating')}
            </div>
          )}
          <p className="text-center text-[12px] text-ds-muted">{t('channelFeishuScanHint')}</p>
          {qrExpireIn > 0 ? (
            <p className="text-[11px] text-ds-faint">
              {t('channelFeishuScanExpires', { seconds: qrExpireIn })}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
