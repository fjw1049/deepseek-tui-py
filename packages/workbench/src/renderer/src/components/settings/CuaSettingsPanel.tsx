import type { AppSettingsPatch, AppSettingsV1 } from '@shared/app-settings'

export function CuaSettingsPanel({ form, onUpdate }: {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}): React.JSX.Element {
  const zh = form.locale === 'zh'
  return <div className="ds-llm-panel__section">
    <h3 className="ds-llm-panel__section-title">{zh ? '电脑控制' : 'Computer use'}</h3>
    <p className="ds-llm-card__meta">{zh
      ? '通过本机 LCU 操作桌面应用。需要先安装 LCU 并授予系统权限；使用聊天中的停止按钮可立即请求停止控制。设置应用后在新聊天中使用。'
      : 'Control desktop apps through local LCU. Install LCU and grant system permissions first. Use Stop in chat to request an immediate stop. Use a new chat after applying settings.'}</p>
    <label className="ds-llm-card">
      <span>{zh ? '启用电脑控制' : 'Enable computer use'}</span>
      <select aria-label={zh ? '启用电脑控制' : 'Enable computer use'}
        value={form.cuaEnabled === undefined ? 'inherit' : String(form.cuaEnabled)}
        onChange={event => onUpdate({ cuaEnabled: event.target.value === 'true' })}>
        <option value="inherit" disabled>{zh ? '继承配置文件（状态未读取）' : 'Inherited from config (state not read)'}</option>
        <option value="false">{zh ? '关闭' : 'Off'}</option>
        <option value="true">{zh ? '开启' : 'On'}</option>
      </select>
    </label>
    <label className="ds-llm-card">
      <span>{zh ? '允许连接外部 Chrome（需要扩展与站点授权）'
        : 'Connect external Chrome (extension and site approval required)'}</span>
      <select aria-label={zh ? '外部 Chrome' : 'External Chrome'}
        value={form.cuaChrome === undefined ? 'inherit' : String(form.cuaChrome)}
        disabled={form.cuaEnabled === false}
        onChange={event => onUpdate({ cuaChrome: event.target.value === 'true' })}>
        <option value="inherit" disabled>{zh ? '继承配置文件（状态未读取）' : 'Inherited from config (state not read)'}</option>
        <option value="false">{zh ? '关闭' : 'Off'}</option>
        <option value="true">{zh ? '开启' : 'On'}</option>
      </select>
    </label>
    <p className="ds-llm-card__meta">{zh
      ? '截图需要支持视觉的主模型，或已配置的视觉辅助模型。后端会在连接前检查已知的模型能力；不满足时不会提供电脑控制工具。'
      : 'Screenshots require a vision-capable model or a configured vision helper. Known model capabilities are checked before connecting; incompatible routes do not expose computer-use tools.'}</p>
  </div>
}
