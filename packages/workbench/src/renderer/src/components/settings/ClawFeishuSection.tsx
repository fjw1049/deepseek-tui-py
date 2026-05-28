import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, ExternalLink, FolderOpen, Loader2, Send } from 'lucide-react'
import type { AppSettingsV1, ClawSettingsPatchV1 } from '@shared/app-settings'
import type { FeishuConfigV1 } from '@shared/ds-gui-api'

type Props = {
  form: AppSettingsV1
  runtimeReady: boolean
  runtimePort: number
  onClawPatch: (patch: ClawSettingsPatchV1) => void
}

type Notice = { tone: 'success' | 'error' | 'info'; message: string }

const FEISHU_OPEN_PLATFORM = 'https://open.feishu.cn/app'

export function ClawFeishuSection({
  form,
  runtimeReady,
  runtimePort,
  onClawPatch
}: Props): ReactElement {
  const { t } = useTranslation('settings')
  const [config, setConfig] = useState<FeishuConfigV1>({
    appId: '',
    appSecret: '',
    domain: 'feishu',
    chatId: ''
  })
  const [configPath, setConfigPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)

  const receiveId = config.chatId.trim()
  const webhookSecret = form.claw.im.secret.trim()
  const inboundUrl = useMemo(
    () => `http://127.0.0.1:${runtimePort}/v1/automation/feishu/inbound`,
    [runtimePort]
  )
  const testSendUrl = useMemo(
    () => `http://127.0.0.1:${runtimePort}/v1/automation/feishu/test-send`,
    [runtimePort]
  )

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const file = await window.dsGui.getFeishuConfig()
      setConfigPath(file.path)
      setConfig(file.config)
    } catch (err) {
      setNotice({
        tone: 'error',
        message: err instanceof Error ? err.message : String(err)
      })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  const handleSave = async (): Promise<void> => {
    setSaving(true)
    setNotice(null)
    try {
      const result = await window.dsGui.setFeishuConfig(config)
      setConfigPath(result.path)
      setNotice({ tone: 'success', message: t('clawFeishuSaved') })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setSaving(false)
    }
  }

  const handleTestSend = async (): Promise<void> => {
    if (!receiveId) {
      setNotice({ tone: 'error', message: t('clawFeishuReceiveIdRequired') })
      return
    }
    if (!runtimeReady) {
      setNotice({ tone: 'error', message: t('clawFeishuNeedRuntime') })
      return
    }
    setTesting(true)
    setNotice(null)
    try {
      const raw = await window.dsGui.runtimeRequest(
        '/v1/automation/feishu/test-send',
        'POST',
        JSON.stringify({ receive_id: receiveId, text: t('clawFeishuTestMessage') })
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
      setNotice({ tone: 'success', message: t('clawFeishuTestOk') })
    } catch (err) {
      setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })
    } finally {
      setTesting(false)
    }
  }

  const copyText = async (text: string): Promise<void> => {
    try {
      await navigator.clipboard.writeText(text)
      setNotice({ tone: 'info', message: t('clawFeishuCopied') })
    } catch {
      setNotice({ tone: 'error', message: t('clawFeishuCopyFailed') })
    }
  }

  const bridgeEnvSnippet = useMemo(() => {
    const token = form.deepseek.runtimeToken.trim() || '<runtime-token>'
    const port = runtimePort
    return [
      `FEISHU_APP_ID=${config.appId || 'cli_xxx'}`,
      `FEISHU_APP_SECRET=${config.appSecret || 'your-secret'}`,
      `FEISHU_DOMAIN=${config.domain || 'feishu'}`,
      `DEEPSEEK_RUNTIME_URL=http://127.0.0.1:${port}`,
      `DEEPSEEK_RUNTIME_TOKEN=${token}`,
      'DEEPSEEK_ALLOW_UNLISTED=true',
      'DEEPSEEK_CHAT_ALLOWLIST='
    ].join('\n')
  }, [config.appId, config.appSecret, config.domain, form.deepseek.runtimeToken, runtimePort])

  return (
    <div className="rounded-2xl border border-ds-border bg-ds-card/95 shadow-sm">
      <div className="border-b border-ds-border-muted px-5 py-3">
        <h2 className="text-[16px] font-semibold text-ds-ink">{t('clawFeishuTitle')}</h2>
        <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('clawFeishuDesc')}</p>
      </div>

      <div className="flex flex-col gap-4 px-5 py-4">
        <ol className="list-decimal space-y-1.5 pl-5 text-[13px] leading-6 text-ds-muted">
          <li>
            {t('clawFeishuStep1')}{' '}
            <button
              type="button"
              className="text-accent underline-offset-2 hover:underline"
              onClick={() => void window.dsGui.openExternal(FEISHU_OPEN_PLATFORM)}
            >
              {t('clawFeishuOpenPlatform')}
              <ExternalLink className="ml-0.5 inline h-3 w-3" />
            </button>
          </li>
          <li>{t('clawFeishuStep2')}</li>
          <li>{t('clawFeishuStep3')}</li>
          <li>{t('clawFeishuStep4')}</li>
        </ol>

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

        {loading ? (
          <div className="flex items-center gap-2 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('loading')}
          </div>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-[13px] font-medium text-ds-ink">{t('clawFeishuAppId')}</span>
                <input
                  className="rounded-xl border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink"
                  value={config.appId}
                  onChange={(e) => setConfig((c) => ({ ...c, appId: e.target.value }))}
                  placeholder="cli_xxxxxxxx"
                  autoComplete="off"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[13px] font-medium text-ds-ink">{t('clawFeishuDomain')}</span>
                <select
                  className="rounded-xl border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink"
                  value={config.domain}
                  onChange={(e) => setConfig((c) => ({ ...c, domain: e.target.value }))}
                >
                  <option value="feishu">feishu（国内）</option>
                  <option value="lark">lark（国际）</option>
                </select>
              </label>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-[13px] font-medium text-ds-ink">{t('clawFeishuAppSecret')}</span>
              <input
                type="password"
                className="rounded-xl border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink"
                value={config.appSecret}
                onChange={(e) => setConfig((c) => ({ ...c, appSecret: e.target.value }))}
                autoComplete="off"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-[13px] font-medium text-ds-ink">{t('clawFeishuReceiveId')}</span>
              <span className="text-[12px] text-ds-faint">{t('clawFeishuReceiveIdDesc')}</span>
              <input
                className="rounded-xl border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink"
                value={receiveId}
                onChange={(e) => setConfig((c) => ({ ...c, chatId: e.target.value }))}
                placeholder="ou_xxxxxxxx 或 oc_xxxxxxxx"
                autoComplete="off"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-[13px] font-medium text-ds-ink">{t('clawFeishuWebhookSecret')}</span>
              <span className="text-[12px] text-ds-faint">{t('clawFeishuWebhookSecretDesc')}</span>
              <input
                type="password"
                className="rounded-xl border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink"
                value={webhookSecret}
                onChange={(e) => onClawPatch({ im: { secret: e.target.value } })}
                autoComplete="off"
              />
            </label>

            <div className="rounded-xl border border-ds-border-muted bg-ds-subtle/40 px-3 py-2">
              <div className="text-[12px] font-medium text-ds-muted">{t('clawFeishuInboundUrl')}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <code className="break-all text-[12px] text-ds-ink">{inboundUrl}</code>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg border border-ds-border px-2 py-1 text-[11px] text-ds-muted hover:bg-ds-hover"
                  onClick={() => void copyText(inboundUrl)}
                >
                  <Copy className="h-3 w-3" />
                  {t('clawFeishuCopy')}
                </button>
              </div>
              <div className="mt-2 text-[12px] text-ds-faint">{t('clawFeishuTestSendHint', { url: testSendUrl })}</div>
            </div>

            <div className="rounded-xl border border-ds-border-muted bg-ds-subtle/40 px-3 py-2">
              <div className="text-[12px] font-medium text-ds-muted">{t('clawFeishuBridgeEnv')}</div>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all text-[11px] text-ds-ink">
                {bridgeEnvSnippet}
              </pre>
              <p className="mt-2 text-[12px] text-ds-faint">{t('clawFeishuBridgeHint')}</p>
            </div>

            {configPath ? (
              <p className="text-[11px] text-ds-faint">
                {t('clawFeishuConfigPath')}: <code>{configPath}</code>
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={saving}
                onClick={() => void handleSave()}
                className="inline-flex items-center gap-1.5 rounded-xl border border-accent/25 bg-accent/10 px-3 py-1.5 text-[13px] font-medium text-accent hover:bg-accent/15 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                {t('clawFeishuSave')}
              </button>
              <button
                type="button"
                disabled={!runtimeReady || testing}
                onClick={() => void handleTestSend()}
                className="inline-flex items-center gap-1.5 rounded-xl border border-ds-border bg-ds-main px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover disabled:opacity-50"
              >
                {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                {t('clawFeishuTestSend')}
              </button>
              <button
                type="button"
                onClick={() => void window.dsGui.openFeishuConfigDir()}
                className="inline-flex items-center gap-1.5 rounded-xl border border-ds-border bg-ds-main px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                {t('clawFeishuOpenConfig')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
