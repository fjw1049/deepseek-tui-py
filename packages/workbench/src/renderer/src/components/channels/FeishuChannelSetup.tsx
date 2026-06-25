import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import QRCode from 'qrcode'
import { Loader2, QrCode, Send, XCircle } from 'lucide-react'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'

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
      {notice ? (
        <p
          className={`rounded-xl px-3 py-2 text-[13px] ${
            notice.tone === 'error'
              ? 'bg-red-500/10 text-red-700 dark:text-red-200'
              : notice.tone === 'success'
                ? 'bg-emerald-500/10 text-emerald-800 dark:text-emerald-200'
                : 'bg-ds-subtle text-ds-muted'
          }`}
        >
          {notice.message}
        </p>
      ) : null}

      <div className="rounded-xl border border-ds-border-muted bg-ds-subtle/40 px-4 py-3">
        <div className="text-[13px] font-medium text-ds-ink">{t('channelFeishuSimpleTitle')}</div>
        <p className="mt-1 text-[12px] leading-5 text-ds-muted">{t('channelFeishuSimpleDesc')}</p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="inline-flex items-center gap-1.5 text-[12px] text-ds-muted">
            <span>{t('channelFeishuTarget')}</span>
            <select
              className="rounded-lg border border-ds-border bg-ds-main px-2 py-1 text-[12px] text-ds-ink"
              value={target}
              disabled={phase === 'scanning'}
              onChange={(e) => setTarget(e.target.value as 'feishu' | 'lark')}
            >
              <option value="feishu">{t('channelFeishuTargetFeishu')}</option>
              <option value="lark">{t('channelFeishuTargetLark')}</option>
            </select>
          </label>
          {phase === 'scanning' ? (
            <button
              type="button"
              onClick={cancelScan}
              className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border px-3 py-1.5 text-[13px] text-ds-muted hover:bg-ds-hover"
            >
              <XCircle className="h-3.5 w-3.5" />
              {t('channelFeishuScanCancel')}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void startScan()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-1.5 text-[13px] font-medium text-accent hover:bg-accent/15"
            >
              <QrCode className="h-3.5 w-3.5" />
              {configured ? t('channelFeishuScanReconnect') : t('channelFeishuScanConnect')}
            </button>
          )}
          {configured && config?.chatId?.trim() ? (
            <button
              type="button"
              disabled={!runtimeReady || testing}
              onClick={() => void runTestSend(config.chatId.trim())}
              className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-main px-3 py-1.5 text-[13px] text-ds-ink hover:bg-ds-hover disabled:opacity-50"
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              {t('channelFeishuTestSend')}
            </button>
          ) : null}
        </div>

        {phase === 'scanning' ? (
          <div className="mt-4 flex flex-col items-center gap-2">
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
    </div>
  )
}
