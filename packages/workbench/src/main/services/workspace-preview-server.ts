import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { createReadStream } from 'node:fs'
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { realpath, stat } from 'node:fs/promises'
import { isHtmlPreviewPath } from '../../shared/html-preview'
import { isImagePreviewPath } from '../../shared/image-preview'
import { isPdfPreviewPath } from '../../shared/document-preview'

type PreviewServerEntry = {
  root: string
  server: Server
  port: number
}

const servers = new Map<string, PreviewServerEntry>()
const startingServers = new Map<string, Promise<PreviewServerEntry>>()

const MIME_BY_EXT: Record<string, string> = {
  '.pdf': 'application/pdf',
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
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel))
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

async function serveFile(root: string, req: IncomingMessage, res: ServerResponse): Promise<void> {
  if (req.headers.host !== `127.0.0.1:${req.socket.localPort}`) {
    sendError(res, 403, 'Forbidden host')
    return
  }
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD')
    sendError(res, 405, 'Method not allowed')
    return
  }
  let pathname: string
  try {
    pathname = decodeURIComponent(new URL(req.url ?? '/', 'http://127.0.0.1').pathname)
  } catch {
    sendError(res, 400, 'Invalid path')
    return
  }
  if (pathname.includes('\0')) {
    sendError(res, 400, 'Invalid path')
    return
  }
  try {
    if (pathname.endsWith('/')) pathname = `${pathname}index.html`
    const relativePath = pathname.replace(/^\/+/, '')
    const candidate = resolve(root, relativePath)
    if (!isWithinRoot(root, candidate)) {
      sendError(res, 404, 'Not found')
      return
    }
    // Resolve symlinks before reading: a lexical path check alone permits
    // links inside the workspace to expose files outside it.
    const target = await realpath(candidate)
    if (!isWithinRoot(root, target) ||
      [relative(root, candidate), relative(root, target)].some((path) =>
        path.split(sep).some((segment) => segment.startsWith('.'))
      )) {
      sendError(res, 404, 'Not found')
      return
    }
    const st = await stat(target)
    if (!st.isFile()) {
      sendError(res, 404, 'Not found')
      return
    }
    res.writeHead(200, {
      'Content-Type': contentTypeFor(candidate),
      'Content-Length': st.size,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff'
    })
    if (req.method === 'HEAD') {
      res.end()
      return
    }
    const stream = createReadStream(target)
    stream.on('error', () => res.destroy())
    res.on('close', () => stream.destroy())
    stream.pipe(res)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    sendError(res, code === 'ENOENT' || code === 'ENOTDIR' ? 404 : 500,
      code === 'ENOENT' || code === 'ENOTDIR' ? 'Not found' : 'Preview server error')
  }
}

async function startServer(root: string): Promise<PreviewServerEntry> {
  const server = createServer((req, res) => { void serveFile(root, req, res) })
  await new Promise<void>((resolvePromise, rejectPromise) => {
    server.once('error', rejectPromise)
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', rejectPromise)
      resolvePromise()
    })
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
  const starting = startingServers.get(root)
  if (starting) return starting
  const pending = startServer(root).then((entry) => {
    servers.set(root, entry)
    return entry
  })
  startingServers.set(root, pending)
  try {
    return await pending
  } finally {
    startingServers.delete(root)
  }
}

export async function getWorkspacePreviewUrl(options: {
  path: string
  workspaceRoot?: string
}): Promise<{ ok: true; url: string; path: string } | { ok: false; message: string }> {
  const workspaceRoot = options.workspaceRoot?.trim() ?? ''
  const rawPath = options.path?.trim()
  if (!rawPath) return { ok: false, message: 'File path is required.' }
  if (!isHtmlPreviewPath(rawPath) && !isImagePreviewPath(rawPath) && !isPdfPreviewPath(rawPath)) {
    return { ok: false, message: 'Only HTML, PDF or image files can be opened in Preview.' }
  }

  try {
    const expanded = expandHomePath(rawPath)
    const absoluteHint = workspaceRoot
      ? resolve(expandHomePath(workspaceRoot))
      : process.cwd()
    const absolute = isAbsolute(expanded) ? resolve(expanded) : resolve(absoluteHint, expanded)
    if (!(await stat(absolute).catch(() => null))?.isFile()) {
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
  await Promise.allSettled([...startingServers.values()])
  const entries = [...servers.values()]
  servers.clear()
  await Promise.all(
    entries.map(
      (entry) =>
        new Promise<void>((resolvePromise) => {
          entry.server.close(() => resolvePromise())
          entry.server.closeAllConnections()
        })
    )
  )
}
