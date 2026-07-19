import type { LucideIcon } from 'lucide-react'
import {
  BarChart3,
  CandlestickChart,
  FileStack,
  GraduationCap,
  Landmark,
  Presentation,
  Puzzle,
  Search,
  Target
} from 'lucide-react'

export type PluginVisual = {
  /** Localized display title (UI headline). */
  title: { zh: string; en: string }
  /** Short card blurb. */
  blurb: { zh: string; en: string }
  /** Longer package-style description for the detail drawer. */
  detail: { zh: string; en: string }
  icon: LucideIcon
  /** Tailwind classes for the icon tile background + foreground. */
  tile: string
}

/**
 * Per-plugin visual identity for the card grid. Unknown plugins fall back to a
 * neutral puzzle tile keyed off the first letter of the id.
 */
const KNOWN: Record<string, PluginVisual> = {
  'deep-research': {
    title: { zh: '深入研究', en: 'Deep Research' },
    blurb: {
      zh: '多轮检索与综合分析，适合调研报告、竞品对比与开放式问题深挖。',
      en: 'Multi-step research and synthesis for reports, comparisons, and open-ended questions.'
    },
    detail: {
      zh: [
        '面向需要「查清楚再说」的任务：围绕一个主题做多轮检索、交叉验证，并把证据整理成可读结论。',
        '典型用途：行业/竞品调研、政策与公开信息梳理、开放式问题的资料深挖，以及需要引用依据的报告初稿。',
        '使用方式：在聊天中通过「使用插件」进入深入研究场景，说明研究问题、范围与产出形式（要点 / 报告 / 对比表）。'
      ].join('\n\n'),
      en: [
        'For tasks that need multi-step research: gather sources, cross-check claims, and synthesize a readable conclusion.',
        'Typical uses: industry/competitor research, policy and public-info digests, open-ended investigations, and evidence-backed report drafts.',
        'How to use: pick “Use plugin” → Deep Research in chat, then state the question, scope, and desired output (bullets / report / comparison).'
      ].join('\n\n')
    },
    icon: Search,
    tile: 'bg-[#3B82F6] text-white'
  },
  'data-analysis': {
    title: { zh: '数据分析', en: 'Data Analysis' },
    blurb: {
      zh: '读取表格与数据文件，做清洗、统计、可视化和结论提炼。',
      en: 'Load tables and datasets for cleaning, stats, charts, and insight summaries.'
    },
    detail: {
      zh: [
        '覆盖从读数到出结论的数据分析流程：数据探查、清洗校验、统计汇总、可视化，以及交互式看板思路。',
        '内置能力方向包括：数据上下文提取、探索分析、数据校验、统计检验、SQL 查询、可视化与仪表盘搭建等。',
        '适合 CSV/表格类问题，例如「这份数据里异常值在哪」「按维度汇总并画图」「帮我写一段可复现的分析步骤」。'
      ].join('\n\n'),
      en: [
        'End-to-end data analysis: explore, clean/validate, aggregate, visualize, and summarize insights.',
        'Capability areas include context extraction, exploratory analysis, validation, stats, SQL, charting, and dashboard workflows.',
        'Best for tabular/CSV questions—outliers, dimensional rollups, charts, and reproducible analysis steps.'
      ].join('\n\n')
    },
    icon: BarChart3,
    tile: 'bg-[#0D9488] text-white'
  },
  'financial-analysis': {
    title: { zh: '金融分析', en: 'Financial Analysis' },
    blurb: {
      zh: '财报解读、指标拆解与财务模型辅助，面向投研与经营分析场景。',
      en: 'Financial statement analysis, KPI breakdowns, and modeling assistance.'
    },
    detail: {
      zh: [
        '面向财务建模与经营/投研分析：三张报表联动、可比公司、DCF/LBO 等模型搭建与检查，以及材料可读性校对。',
        '常见产出：财务假设梳理、估值框架、模型检查清单、竞争格局要点，以及面向汇报的数字故事线。',
        '使用前请准备尽量完整的输入（财报摘要、关键假设、对标公司）；涉及实盘投资决策时，结论仅作研究辅助。'
      ].join('\n\n'),
      en: [
        'Financial modeling and analysis: three-statement linkage, comps, DCF/LBO scaffolding and checks, plus deck/model review helpers.',
        'Common outputs: assumption maps, valuation frames, model checklists, competitive notes, and number-led narratives.',
        'Provide statements/assumptions/peers when possible; treat outputs as research assistance, not investment advice.'
      ].join('\n\n')
    },
    icon: Landmark,
    tile: 'bg-[#059669] text-white'
  },
  'ppt-implement': {
    title: { zh: '智能 PPT', en: 'PPT Implement' },
    blurb: {
      zh: '根据主题与素材生成演示结构、页面要点与可落地的幻灯片内容。',
      en: 'Turn topics and materials into slide structure, talking points, and deck content.'
    },
    detail: {
      zh: [
        '把主题、提纲或原始素材转成可落地的演示内容：故事线、分页结构、每页标题/要点，以及讲解备注草稿。',
        '适合汇报、路演、方案讲解等场景；可先约定受众、时长与风格（简洁 / 数据向 / 故事向），再迭代页面。',
        '建议一次性提供目标、关键数字与必须出现的信息点；需要视觉稿时，可在结构稳定后再细化版式。'
      ].join('\n\n'),
      en: [
        'Turn a topic, outline, or raw notes into a presentable deck: narrative, slide map, titles/bullets, and speaker-note drafts.',
        'Works well for reviews, pitches, and proposals—set audience, length, and tone, then iterate page by page.',
        'Share goals, must-have facts, and key numbers up front; refine layout after the structure settles.'
      ].join('\n\n')
    },
    icon: Presentation,
    tile: 'bg-[#E11D48] text-white'
  },
  'document-skills': {
    title: { zh: '文档技能', en: 'Document Skills' },
    blurb: {
      zh: 'Word / Excel / PPTX / PDF 的创建、读写、编辑与转换，覆盖日常办公文档产出。',
      en: 'Create, read, edit, and convert Word, Excel, PPTX, and PDF for everyday office work.'
    },
    detail: {
      zh: [
        '面向 Office 与 PDF 交付物：报告与合同（docx）、表格清洗与图表（xlsx/csv）、可编辑演示稿（pptx），以及 PDF 合并拆分、表单、加密与 OCR。',
        '内置 skill：xlsx、docx、pptx、pptx-generator（JSON→PPTX）、pdf、pdfkit-py（命令型全场景工具箱）。',
        '使用方式：在聊天中挂载 @plugin:document-skills，说明输入文件与期望格式。需要 HTML「智能 PPT」专家流时请改用 ppt-implement，不要与本插件的 pptx 能力混淆。'
      ].join('\n\n'),
      en: [
        'For Office and PDF deliverables: Word reports (docx), spreadsheet clean-up and charts (xlsx/csv), editable decks (pptx), plus PDF merge/split, forms, encryption, and OCR.',
        'Bundled skills: xlsx, docx, pptx, pptx-generator (JSON→PPTX), pdf, and pdfkit-py (command-style PDF toolkit).',
        'How to use: mount @plugin:document-skills in chat and state inputs plus target format. For the HTML “smart PPT” expert pipeline, use ppt-implement instead of this plugin’s pptx skills.'
      ].join('\n\n')
    },
    icon: FileStack,
    tile: 'bg-[#4F46E5] text-white'
  },
  'product-management': {
    title: { zh: '产品管理', en: 'Product Management' },
    blurb: {
      zh: '需求梳理、竞品分析与产品文档辅助，覆盖从洞察到方案的工作流。',
      en: 'Requirements, competitive analysis, and product docs from insight to proposal.'
    },
    detail: {
      zh: [
        '覆盖产品经理日常文档与决策辅助：需求/功能规格、用户研究综合、竞品分析、路线图与冲刺规划、指标跟踪与干系人沟通。',
        '可从模糊想法开始，逐步收敛为问题定义、方案选项、验收标准与沟通稿；也适合复盘已有 PRD/路线图。',
        '输入越具体（用户、场景、约束、成功指标）产出越可执行；涉及对外承诺时请再人工确认优先级与资源。'
      ].join('\n\n'),
      en: [
        'Day-to-day PM assistance: feature specs, research synthesis, competitive analysis, roadmap/sprint planning, metrics, and stakeholder comms.',
        'Start from a fuzzy idea and converge to problem framing, options, acceptance criteria, and update notes—or critique existing PRDs/roadmaps.',
        'Clearer inputs (users, scenarios, constraints, success metrics) yield more actionable drafts; re-check priorities before external commitments.'
      ].join('\n\n')
    },
    icon: Target,
    tile: 'bg-[#D97706] text-white'
  },
  'equity-research': {
    title: { zh: '股票研究', en: 'Equity Research' },
    blurb: {
      zh: '个股基本面与行业研究辅助，整理要点、风险与跟踪清单。',
      en: 'Equity and sector research helpers for theses, risks, and watchlists.'
    },
    detail: {
      zh: [
        '面向权益研究工作流：公司一页纸、财报解读/前瞻、可比与 DCF 框架、行业概览、事件情景、多空观点与持仓风险梳理等。',
        '也可用于晨会要点、投资备忘、论点跟踪与催化剂日历类整理，帮助把碎片信息收成可复查的研究材料。',
        '结论依赖公开信息与你提供的假设；不构成投资建议，关键数字与公告请以一手来源为准。'
      ].join('\n\n'),
      en: [
        'Equity-research workflows: tearsheets, earnings notes/previews, comps/DCF frames, sector overviews, event scenarios, long/short pitches, and portfolio-risk notes.',
        'Also useful for morning notes, memos, thesis tracking, and catalyst calendars—turning scraps into reviewable research packs.',
        'Outputs depend on public info and your assumptions; not investment advice—verify numbers against primary sources.'
      ].join('\n\n')
    },
    icon: CandlestickChart,
    tile: 'bg-[#1D4ED8] text-white'
  },
  'academic-research-suite': {
    title: { zh: '学术研究', en: 'Academic Research' },
    blurb: {
      zh: '文献阅读、论点整理与学术写作辅助，适合论文与课题研究。',
      en: 'Literature review, argument structuring, and academic writing assistance.'
    },
    detail: {
      zh: [
        '学术研究套件：深度文献调研、论文审阅、论文写作、实验设计辅助，以及端到端研究流水线编排。',
        '适合开题调研、相关工作梳理、论点与结构打磨、实验方案草稿，以及按章节推进的写作迭代。',
        '请注明学科、引用规范与目标刊物/课程要求；涉及原创实验与投稿合规时，需自行核对伦理与查重要求。'
      ].join('\n\n'),
      en: [
        'Academic suite: deep literature research, paper review, writing help, experiment-design assistance, and end-to-end research pipeline support.',
        'Useful for topic surveys, related-work maps, argument/structure polishing, experiment drafts, and chapter-by-chapter writing.',
        'State field, citation style, and venue/course constraints; verify ethics and originality requirements before submission.'
      ].join('\n\n')
    },
    icon: GraduationCap,
    tile: 'bg-[#0F766E] text-white'
  }
}

const FALLBACK_TILES = [
  'bg-[#2563EB] text-white',
  'bg-[#0F766E] text-white',
  'bg-[#B45309] text-white',
  'bg-[#BE123C] text-white',
  'bg-[#1E3A5F] text-white',
  'bg-[#365314] text-white'
]

export function pluginVisual(pluginId: string): PluginVisual {
  const key = pluginId.trim().toLowerCase()
  const known = KNOWN[key]
  if (known) return known
  const hash = [...key].reduce((acc, ch) => acc + ch.charCodeAt(0), 0)
  return {
    title: { zh: pluginId, en: pluginId },
    blurb: { zh: '', en: '' },
    detail: { zh: '', en: '' },
    icon: Puzzle,
    tile: FALLBACK_TILES[hash % FALLBACK_TILES.length] ?? FALLBACK_TILES[0]
  }
}

export function pluginDisplayTitle(pluginId: string, locale: string): string {
  const visual = pluginVisual(pluginId)
  return locale.toLowerCase().startsWith('zh') ? visual.title.zh : visual.title.en
}

/** Prefer curated blurb; fall back to package description. */
export function pluginDisplaySummary(
  pluginId: string,
  locale: string,
  description?: string
): string {
  const visual = pluginVisual(pluginId)
  const blurb = locale.toLowerCase().startsWith('zh') ? visual.blurb.zh : visual.blurb.en
  const trimmed = description?.trim() ?? ''
  if (blurb) return blurb
  return trimmed
}

/** Longer package description for the detail drawer. */
export function pluginDisplayDetail(
  pluginId: string,
  locale: string,
  description?: string
): string {
  const visual = pluginVisual(pluginId)
  const detail = locale.toLowerCase().startsWith('zh') ? visual.detail.zh : visual.detail.en
  const trimmed = description?.trim() ?? ''
  if (detail && trimmed && detail !== trimmed && !detail.includes(trimmed)) {
    return `${detail}\n\n${trimmed}`
  }
  if (detail) return detail
  return trimmed
}

export function countPluginComponents(components: {
  skills: boolean
  hooks: boolean
  mcp_servers: boolean
  commands: boolean
  agents: boolean
  rules: boolean
}): number {
  return [
    components.skills,
    components.hooks,
    components.mcp_servers,
    components.commands,
    components.agents,
    components.rules
  ].filter(Boolean).length
}
