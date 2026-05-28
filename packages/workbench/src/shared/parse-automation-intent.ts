/**
 * Rule-based NL → durable automation (RRULE + agent prompt).
 * Used by the workbench composer "自动化" surface; backend scheduler is unchanged.
 */

export type AutomationScheduleKind = 'daily' | 'weekly' | 'hourly'

export type ParsedAutomationSchedule = {
  kind: AutomationScheduleKind
  /** Local time for daily/weekly (HH:MM). */
  timeOfDay: string
  /** Weekday tokens MO..SU for weekly-only rules. */
  weekdays: string[] | null
  /** For hourly schedules. */
  intervalHours: number
  rrule: string
  label: string
}

export type ParsedAutomationIntent = {
  name: string
  schedule: ParsedAutomationSchedule
  /** Agent task prompt (not the user's scheduling phrase alone). */
  agentPrompt: string
  deliveryMode: 'email' | 'feishu'
}

export type ParseAutomationIntentResult =
  | { ok: true; intent: ParsedAutomationIntent }
  | { ok: false; error: string }

const WEEKDAY_MAP: Record<string, string> = {
  一: 'MO',
  二: 'TU',
  三: 'WE',
  四: 'TH',
  五: 'FR',
  六: 'SA',
  日: 'SU',
  天: 'SU'
}

const ALL_WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const

/** 九点、十点、十一点、十二点 → hour */
const ZH_HOUR_WORD: Record<string, number> = {
  零: 0,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
  十一: 11,
  十二: 12
}

function parseZhHourToken(token: string): number | null {
  const t = token.trim()
  if (!t) return null
  if (t in ZH_HOUR_WORD) return ZH_HOUR_WORD[t]
  if (t.startsWith('十')) {
    const rest = t.slice(1)
    if (!rest) return 10
    const low = ZH_HOUR_WORD[rest]
    return low != null ? 10 + low : null
  }
  if (t.endsWith('十') && t.length >= 2) {
    const high = ZH_HOUR_WORD[t.slice(0, -1)]
    return high != null && high > 0 ? high * 10 : null
  }
  if (t.includes('十')) {
    const [a, b] = t.split('十')
    const hi = a ? (ZH_HOUR_WORD[a] ?? null) : 1
    const lo = b ? (ZH_HOUR_WORD[b] ?? null) : 0
    if (hi == null || lo == null) return null
    return hi * 10 + lo
  }
  return null
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

function normalizeTimeOfDay(hour: number, minute: number): string | null {
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null
  return `${pad2(hour)}:${pad2(minute)}`
}

/** Parse 十点 / 10点30 / 10:30 / 10：30 */
export function parseTimeOfDay(text: string): string | null {
  const colon = text.match(/(\d{1,2})\s*[:：]\s*(\d{1,2})/)
  if (colon) {
    return normalizeTimeOfDay(Number(colon[1]), Number(colon[2]))
  }
  const zhNum = text.match(/(\d{1,2})\s*点\s*(\d{1,2})?\s*分?/)
  if (zhNum) {
    const minute = zhNum[2] ? Number(zhNum[2]) : 0
    return normalizeTimeOfDay(Number(zhNum[1]), minute)
  }
  const zhWord = text.match(/((?:十[一二三四五六七八九]?)|(?:[一二两三四五六七八九]十[一二三四五六七八九]?)|(?:[一二两三四五六七八九]|十{1,2}))\s*点\s*(\d{1,2}|[一二三四五六七八九]{1,2})?\s*分?/)
  if (zhWord) {
    const hour = parseZhHourToken(zhWord[1])
    if (hour != null) {
      const minuteRaw = zhWord[2]
      const minute =
        minuteRaw && /^\d+$/.test(minuteRaw)
          ? Number(minuteRaw)
          : minuteRaw
            ? (parseZhHourToken(minuteRaw) ?? 0)
            : 0
      return normalizeTimeOfDay(hour, minute)
    }
  }
  const period = text.match(/(早上|上午|中午|下午|晚上|傍晚)\s*(\d{1,2})\s*点\s*(\d{1,2})?\s*分?/)
  if (period) {
    let hour = Number(period[2])
    const minute = period[3] ? Number(period[3]) : 0
    const bucket = period[1]
    if ((bucket === '下午' || bucket === '晚上' || bucket === '傍晚') && hour < 12) hour += 12
    if (bucket === '中午' && hour < 11) hour = 12
    return normalizeTimeOfDay(hour, minute)
  }
  return null
}

function buildDailyRrule(timeOfDay: string): ParsedAutomationSchedule {
  const [h, m] = timeOfDay.split(':').map((x) => Number(x))
  const byday = ALL_WEEKDAYS.join(',')
  return {
    kind: 'daily',
    timeOfDay,
    weekdays: [...ALL_WEEKDAYS],
    intervalHours: 1,
    rrule: `FREQ=WEEKLY;BYDAY=${byday};BYHOUR=${h};BYMINUTE=${m}`,
    label: `每天 ${timeOfDay}`
  }
}

function buildWeeklyRrule(timeOfDay: string, weekdays: string[]): ParsedAutomationSchedule {
  const [h, m] = timeOfDay.split(':').map((x) => Number(x))
  const byday = weekdays.join(',')
  const zhDays = weekdays
    .map((d) => Object.entries(WEEKDAY_MAP).find(([, v]) => v === d)?.[0])
    .filter(Boolean)
    .join('、')
  return {
    kind: 'weekly',
    timeOfDay,
    weekdays,
    intervalHours: 1,
    rrule: `FREQ=WEEKLY;BYDAY=${byday};BYHOUR=${h};BYMINUTE=${m}`,
    label: `每周${zhDays} ${timeOfDay}`
  }
}

function buildHourlyRrule(intervalHours: number): ParsedAutomationSchedule {
  return {
    kind: 'hourly',
    timeOfDay: '00:00',
    weekdays: null,
    intervalHours,
    rrule: `FREQ=HOURLY;INTERVAL=${intervalHours}`,
    label: intervalHours === 1 ? '每小时' : `每 ${intervalHours} 小时`
  }
}

export function parseAutomationSchedule(text: string): ParsedAutomationSchedule | null {
  const raw = text.trim()
  if (!raw) return null

  const hourlyEvery = raw.match(/每\s*(\d+)\s*个?\s*小时/)
  if (hourlyEvery) {
    const n = Math.max(1, Math.min(24, Number(hourlyEvery[1]) || 1))
    return buildHourlyRrule(n)
  }
  if (/每小时|每个小时/.test(raw)) {
    return buildHourlyRrule(1)
  }

  const time = parseTimeOfDay(raw) ?? '09:00'

  const weeklyOne = raw.match(/每周\s*([一二三四五六日天])/)
  if (weeklyOne) {
    const token = WEEKDAY_MAP[weeklyOne[1]]
    if (token) return buildWeeklyRrule(time, [token])
  }

  if (/每天|每日|天天|每天早上|每日早上/.test(raw)) {
    return buildDailyRrule(time)
  }

  // "十点发…" without 每天 → treat as daily at that time (common phrasing)
  if (parseTimeOfDay(raw) && /发给我|发到|邮件|邮箱|推送|通知/.test(raw)) {
    return buildDailyRrule(time)
  }

  return null
}

function detectDeliveryMode(text: string): 'email' | 'feishu' {
  if (/飞书|feishu|lark/i.test(text) && !/邮箱|邮件|email/i.test(text)) {
    return 'feishu'
  }
  if (/发到飞书|发飞书|推送飞书|通知飞书/.test(text)) {
    return 'feishu'
  }
  return 'email'
}

function buildStockPrompt(subject: string, userText: string, deliveryMode: 'email' | 'feishu'): string {
  const deliveryHint =
    deliveryMode === 'feishu'
      ? '结果将投递到飞书，用中文简洁输出。'
      : '结果将邮件投递，用中文输出。'
  if (/小米/.test(subject)) {
    return (
      '你是每日股票简报助手（自动化任务）。查询小米集团港股 01810（1810.HK）行情：\n' +
      '优先 fetch_url 一次 https://quote.eastmoney.com/hk/01810.html ；失败可再试一次 Google Finance 1810:HKG。\n' +
      `${deliveryHint}现价、涨跌额/涨跌幅、行情时间、数据来源。禁止编造价格。\n` +
      `用户原话：${userText.trim()}`
    )
  }
  return (
    `你是自动化简报助手。根据用户描述完成一次信息收集与摘要，${deliveryHint}\n` +
    '优先使用 fetch_url / web_search，控制工具调用次数，不要编造数据。\n' +
    `用户任务：${userText.trim()}`
  )
}

function automationName(text: string, schedule: ParsedAutomationSchedule): string {
  const base = text.replace(/\s+/g, ' ').trim().slice(0, 32)
  if (base.length >= 4) return base
  return `自动化 · ${schedule.label}`
}

export function parseAutomationIntent(text: string): ParseAutomationIntentResult {
  const trimmed = text.trim()
  if (!trimmed) {
    return { ok: false, error: '请输入自动化任务描述，例如：每天十点把小米股票发到我邮箱' }
  }

  const schedule = parseAutomationSchedule(trimmed)
  if (!schedule) {
    return {
      ok: false,
      error: '未能识别时间规则。请包含「每天十点」「每周一 9:00」「每小时」等说法。'
    }
  }

  const deliveryMode = detectDeliveryMode(trimmed)
  const intent: ParsedAutomationIntent = {
    name: automationName(trimmed, schedule),
    schedule,
    agentPrompt: buildStockPrompt(trimmed, trimmed, deliveryMode),
    deliveryMode
  }
  return { ok: true, intent }
}
