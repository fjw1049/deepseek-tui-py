import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { realpath } from 'node:fs/promises'
import { isHtmlPreviewPath } from '../../shared/html-preview'
import { isImagePreviewPath } from '../../shared/image-preview'

type PreviewServerEntry = {
  root: string
  server: Server
  port: number
}

const servers = new Map<string, PreviewServerEntry>()

const MIME_BY_EXT: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.xhtml': 'application/xhtml+xml; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json',
  '.txt': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
}

function expandHomePath(value: string): string {
  if (value === '~') return process.env.HOME || process.env.USERPROFILE || value
  if (value.startsWith('~/') || value.startsWith('~\\')) {
    const home = process.env.HOME || process.env.USERPROFILE || ''
    return home ? join(home, value.slice(2)) : value
  }
  return value
}

async function canonicalPath(targetPath: string): Promise<string> {
  try {
    return await realpath(targetPath)
  } catch {
    return resolve(targetPath)
  }
}

function isWithinRoot(root: string, targetPath: string): boolean {
  const rel = relative(root, targetPath)
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

function contentTypeFor(filePath: string): string {
  return MIME_BY_EXT[extname(filePath).toLowerCase()] ?? 'application/octet-stream'
}

function sendError(res: ServerResponse, status: number, message: string): void {
  res.writeHead(status, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Cache-Control': 'no-store'
  })
  res.end(message)
}

function serveFile(root: string, req: IncomingMessage, res: ServerResponse): void {
  try {
    const rawUrl = req.url ?? '/'
    const parsed = new URL(rawUrl, 'http://127.0.0.1')
    let pathname = decodeURIComponent(parsed.pathname)
    if (pathname.includes('\0')) {
      sendError(res, 400, 'Invalid path')
      return
    }
    if (pathname.endsWith('/')) pathname = `${pathname}index.html`
    const relativePath = pathname.replace(/^\/+/, '')
    const candidate = resolve(root, relativePath)
    if (!isWithinRoot(root, candidate) || !existsSync(candidate)) {
      sendError(res, 404, 'Not found')
      return
    }
    const st = statSync(candidate)
    if (!st.isFile()) {
      sendError(res, 404, 'Not found')
      return
    }
    res.writeHead(200, {
      'Content-Type': contentTypeFor(candidate),
      'Content-Length': st.size,
      'Cache-Control': 'no-store',
      // Keep preview pages from being framed by untrusted origins; the
      // Workbench webview/iframe loads 127.0.0.1 which is same-site enough.
      'X-Content-Type-Options': 'nosniff'
    })
    createReadStream(candidate).pipe(res)
  } catch {
    sendError(res, 500, 'Preview server error')
  }
}

async function startServer(root: string): Promise<PreviewServerEntry> {
  const server = createServer((req, res) => serveFile(root, req, res))
  await new Promise<void>((resolvePromise, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(0, '127.0.0.1', () => resolvePromise())
  })
  const address = server.address()
  if (!address || typeof address === 'string') {
    server.close()
    throw new Error('Failed to bind workspace preview server')
  }
  return { root, server, port: address.port }
}

export async function ensureWorkspacePreviewServer(
  workspaceRoot: string
): Promise<PreviewServerEntry> {
  const root = await canonicalPath(resolve(expandHomePath(workspaceRoot.trim())))
  const existing = servers.get(root)
  if (existing) return existing
  const entry = await startServer(root)
  servers.set(root, entry)
  return entry
}

export async function getWorkspacePreviewUrl(options: {
  path: string
  workspaceRoot?: string
}): Promise<{ ok: true; url: string; path: string } | { ok: false; message: string }> {
  const workspaceRoot = options.workspaceRoot?.trim() ?? ''
  const rawPath = options.path?.trim()
  if (!rawPath) return { ok: false, message: 'File path is required.' }
  if (!isHtmlPreviewPath(rawPath) && !isImagePreviewPath(rawPath)) {
    return { ok: false, message: 'Only HTML or image files can be opened in Preview.' }
  }

  try {
    const expanded = expandHomePath(rawPath)
    const absoluteHint = workspaceRoot
      ? resolve(expandHomePath(workspaceRoot))
      : process.cwd()
    const absolute = isAbsolute(expanded) ? resolve(expanded) : resolve(absoluteHint, expanded)
    if (!existsSync(absolute) || !statSync(absolute).isFile()) {
      return { ok: false, message: `File not found: ${rawPath}` }
    }
    const target = await canonicalPath(absolute)

    let root: string | null = null
    if (workspaceRoot) {
      const candidateRoot = await canonicalPath(resolve(expandHomePath(workspaceRoot)))
      if (isWithinRoot(candidateRoot, target)) {
        root = candidateRoot
      }
    }
    // If the file is absolute but outside the declared workspace root, still
    // preview it by serving from its parent directory. Agents often write
    // artifacts to absolute paths; relative assets next to the HTML keep
    // working. Relative paths still require a workspace root.
    if (!root) {
      if (!isAbsolute(expanded)) {
        return {
          ok: false,
          message: workspaceRoot
            ? 'Path must stay within the selected workspace.'
            : 'Workspace root is required for relative paths.'
        }
      }
      root = await canonicalPath(dirname(target))
    }

    const entry = await ensureWorkspacePreviewServer(root)
    const rel = relative(root, target).split(sep).join('/')
    const url = `http://127.0.0.1:${entry.port}/${rel.split('/').map(encodeURIComponent).join('/')}`
    return { ok: true, url, path: target }
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : 'Failed to open HTML preview.'
    }
  }
}

export async function shutdownWorkspacePreviewServers(): Promise<void> {
  const entries = [...servers.values()]
  servers.clear()
  await Promise.all(
    entries.map(
      (entry) =>
        new Promise<void>((resolvePromise) => {
          entry.server.close(() => resolvePromise())
        })
    )
  )
}
