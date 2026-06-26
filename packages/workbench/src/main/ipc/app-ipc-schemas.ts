import { z } from 'zod'

const MAX_BODY_BYTES = 2_000_000
const MAX_PATH_LENGTH = 4_096
const MAX_URL_LENGTH = 4_096
const MAX_ID_LENGTH = 256
const MAX_BRANCH_LENGTH = 255
const MAX_COMMIT_MESSAGE_LENGTH = 5_000
const MAX_GIT_PATHS = 500
const MAX_EDITOR_ID_LENGTH = 64
const MAX_NOTIFICATION_TITLE_LENGTH = 200
const MAX_NOTIFICATION_BODY_LENGTH = 5_000
const MAX_SKILL_FILE_BYTES = 1_000_000
const MAX_CONFIG_FILE_BYTES = 2_000_000

const SAFE_OPEN_EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

function trimmedString(max: number): z.ZodString {
  return z.string().trim().min(1).max(max)
}

function optionalTrimmedString(max: number): z.ZodOptional<z.ZodString> {
  return trimmedString(max).optional()
}

export function isSafeOpenExternalUrl(value: string): boolean {
  try {
    const parsed = new URL(value)
    return SAFE_OPEN_EXTERNAL_PROTOCOLS.has(parsed.protocol)
  } catch {
    return false
  }
}

export const defaultPathSchema = optionalTrimmedString(MAX_PATH_LENGTH)

export const runtimeRequestPayloadSchema = z
  .object({
    path: trimmedString(MAX_URL_LENGTH).transform((value) =>
      value.startsWith('/') ? value : `/${value}`
    ),
    method: z.enum(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']).optional(),
    body: z.string().max(MAX_BODY_BYTES).optional()
  })
  .strict()

export const skillSaveFilePayloadSchema = z
  .object({
    rootPath: trimmedString(MAX_PATH_LENGTH),
    skillName: trimmedString(128),
    content: z.string().max(MAX_SKILL_FILE_BYTES)
  })
  .strict()

export const rootPathSchema = trimmedString(MAX_PATH_LENGTH)
export const deepseekConfigContentSchema = z.string().max(MAX_CONFIG_FILE_BYTES)

export const feishuConfigPayloadSchema = z
  .object({
    appId: z.string().trim().max(200),
    appSecret: z.string().trim().max(500),
    domain: z.string().trim().max(50),
    chatId: z.string().trim().max(200)
  })
  .strict()

export const wecomConfigPayloadSchema = z
  .object({
    webhookKey: z.string().trim().min(1).max(500)
  })
  .strict()

export const feishuRegisterStartPayloadSchema = z
  .object({
    target: z.enum(['feishu', 'lark']).optional()
  })
  .strict()

export const emailSecretPayloadSchema = z
  .object({
    password: z.string().trim().min(1).max(500)
  })
  .strict()

export const workspaceRootSchema = trimmedString(MAX_PATH_LENGTH)
export const gitBranchPayloadSchema = z
  .object({
    workspaceRoot: workspaceRootSchema,
    branch: trimmedString(MAX_BRANCH_LENGTH)
  })
  .strict()

export const gitCommitPayloadSchema = z
  .object({
    workspaceRoot: workspaceRootSchema,
    message: trimmedString(MAX_COMMIT_MESSAGE_LENGTH),
    paths: z.array(trimmedString(MAX_PATH_LENGTH)).max(MAX_GIT_PATHS).optional()
  })
  .strict()

export const gitCommitPathsPayloadSchema = z
  .object({
    workspaceRoot: workspaceRootSchema,
    paths: z.array(trimmedString(MAX_PATH_LENGTH)).max(MAX_GIT_PATHS).optional()
  })
  .strict()

export const openEditorPathPayloadSchema = z
  .object({
    path: trimmedString(MAX_PATH_LENGTH),
    workspaceRoot: optionalTrimmedString(MAX_PATH_LENGTH),
    editorId: optionalTrimmedString(MAX_EDITOR_ID_LENGTH),
    line: z.number().int().positive().max(1_000_000).optional(),
    column: z.number().int().positive().max(1_000_000).optional()
  })
  .strict()

export const terminalCreateOptionsSchema = z
  .object({
    cwd: trimmedString(MAX_PATH_LENGTH),
    cols: z.number().int().positive().max(1_000).optional(),
    rows: z.number().int().positive().max(1_000).optional()
  })
  .strict()

export const terminalInputPayloadSchema = z
  .object({
    sessionId: trimmedString(MAX_ID_LENGTH),
    data: z.string().max(64_000)
  })
  .strict()

export const terminalResizePayloadSchema = z
  .object({
    sessionId: trimmedString(MAX_ID_LENGTH),
    cols: z.number().int().positive().max(1_000),
    rows: z.number().int().positive().max(1_000)
  })
  .strict()

export const terminalLifecyclePayloadSchema = z
  .object({
    sessionId: trimmedString(MAX_ID_LENGTH)
  })
  .strict()

export const workspaceFileWritePayloadSchema = z
  .object({
    path: trimmedString(MAX_PATH_LENGTH),
    workspaceRoot: optionalTrimmedString(MAX_PATH_LENGTH),
    content: z.string().max(MAX_BODY_BYTES)
  })
  .strict()

export const workspaceListDirectoryPayloadSchema = z
  .object({
    workspaceRoot: trimmedString(MAX_PATH_LENGTH),
    directoryPath: z.string().trim().max(MAX_PATH_LENGTH).optional()
  })
  .strict()

export const workspaceFileTargetPayloadSchema = z
  .object({
    path: trimmedString(MAX_PATH_LENGTH),
    workspaceRoot: optionalTrimmedString(MAX_PATH_LENGTH),
    line: z.number().int().positive().max(1_000_000).optional(),
    column: z.number().int().positive().max(1_000_000).optional()
  })
  .strict()

export const shellOpenExternalUrlSchema = trimmedString(MAX_URL_LENGTH).refine(
  isSafeOpenExternalUrl,
  { message: 'Only http, https, and mailto URLs are allowed.' }
)

export const notificationPayloadSchema = z
  .object({
    threadId: optionalTrimmedString(MAX_ID_LENGTH),
    title: trimmedString(MAX_NOTIFICATION_TITLE_LENGTH),
    body: trimmedString(MAX_NOTIFICATION_BODY_LENGTH)
  })
  .strict()

export const logErrorPayloadSchema = z
  .object({
    category: trimmedString(128),
    message: trimmedString(2_000),
    detail: z.unknown().optional()
  })
  .strict()

export const petResolveSpritesheetPayloadSchema = z
  .object({
    slug: optionalTrimmedString(80)
  })
  .strict()

export const sseStartPayloadSchema = z
  .object({
    threadId: trimmedString(MAX_ID_LENGTH),
    sinceSeq: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
    streamId: optionalTrimmedString(MAX_ID_LENGTH)
  })
  .strict()

export const streamIdSchema = trimmedString(MAX_ID_LENGTH)

export const workspacePickFilesPayloadSchema = z
  .object({
    workspaceRoot: workspaceRootSchema,
    imagesOnly: z.boolean().optional()
  })
  .strict()

export const trendingPeriodSchema = z.enum(['daily', 'weekly', 'monthly'])

export const usageRangeSchema = z.enum(['7d', '30d', '90d'])

export const usageQueryPayloadSchema = z
  .object({
    range: usageRangeSchema.optional(),
    locale: z.string().trim().max(32).optional()
  })
  .strict()

export const usagePruneProviderPayloadSchema = z
  .object({
    providerId: trimmedString(MAX_ID_LENGTH)
  })
  .strict()

export const usagePruneEndpointModelPayloadSchema = z
  .object({
    providerId: trimmedString(MAX_ID_LENGTH),
    modelId: trimmedString(MAX_ID_LENGTH)
  })
  .strict()
