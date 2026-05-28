import { describe, expect, it } from 'vitest'
import {
  AUTOMATION_COMPOSER_HEADING,
  CLAW_CURRENT_USER_REQUEST_HEADING,
  buildAutomationComposerPrompt,
  unwrapAutomationComposerPromptForDisplay,
  unwrapClawUserPromptForDisplay
} from './app-settings'

describe('unwrapAutomationComposerPromptForDisplay', () => {
  it('strips playbook wrapper and keeps user text only', () => {
    const wrapped = buildAutomationComposerPrompt('一分钟后发到飞书', {
      feishuChatId: 'oc_test',
      userTimezone: 'Asia/Shanghai'
    })
    expect(wrapped).toContain(AUTOMATION_COMPOSER_HEADING)
    expect(unwrapClawUserPromptForDisplay(wrapped)).toBe('一分钟后发到飞书')
    expect(unwrapAutomationComposerPromptForDisplay(wrapped)).toBe('一分钟后发到飞书')
  })

  it('leaves ordinary messages unchanged', () => {
    const plain = '普通对话消息'
    expect(unwrapClawUserPromptForDisplay(plain)).toBe(plain)
  })

  it('playbook forbids tool_search and lists direct tool names', () => {
    const wrapped = buildAutomationComposerPrompt('两分钟后总结', {
      feishuChatId: 'oc_test',
      userTimezone: 'Asia/Shanghai'
    })
    expect(wrapped).toContain('Do NOT call tool_search_tool_regex')
    expect(wrapped).toContain('current_time')
    expect(wrapped).toContain('automation_create')
  })
})
