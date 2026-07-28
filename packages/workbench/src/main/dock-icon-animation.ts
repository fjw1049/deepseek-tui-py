import { app, nativeImage, type NativeImage } from 'electron'
import { fileURLToPath } from 'node:url'

const FRAME_MS = Math.round(2800 / 24) // match in-app 2.8s cycle / 24 frames

const frameModules = import.meta.glob('../asset/img/app-icon-anim/frame-*.png', {
  eager: true,
  import: 'default'
}) as Record<string, string>

let frames: NativeImage[] = []
let timer: ReturnType<typeof setInterval> | null = null
let frameIndex = 0

function imageFromAssetUrl(url: string): NativeImage {
  if (url.startsWith('data:')) return nativeImage.createFromDataURL(url)
  if (url.startsWith('file:')) return nativeImage.createFromPath(fileURLToPath(url))
  return nativeImage.createFromPath(url)
}

function loadFrames(): NativeImage[] {
  return Object.entries(frameModules)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, url]) => imageFromAssetUrl(url))
    .filter((img) => !img.isEmpty())
}

/** macOS Dock: cycle largest↔smallest swap frames. No-op elsewhere. */
export function startDockIconAnimation(): void {
  if (process.platform !== 'darwin' || !app.dock) return
  if (timer) return

  frames = loadFrames()
  if (frames.length === 0) {
    console.warn('[dock-icon-animation] no frames loaded')
    return
  }

  frameIndex = 0
  app.dock.setIcon(frames[0]!)
  timer = setInterval(() => {
    if (!app.dock || frames.length === 0) return
    frameIndex = (frameIndex + 1) % frames.length
    app.dock.setIcon(frames[frameIndex]!)
  }, FRAME_MS)
}

export function stopDockIconAnimation(restIcon?: NativeImage): void {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  if (process.platform === 'darwin' && app.dock && restIcon && !restIcon.isEmpty()) {
    app.dock.setIcon(restIcon)
  }
}
