export const THREAD_MARQUEE_PIXELS_PER_SECOND = 42

export function threadMarqueeDurationMs(distance: number): number {
  return (distance / THREAD_MARQUEE_PIXELS_PER_SECOND) * 1_000
}
