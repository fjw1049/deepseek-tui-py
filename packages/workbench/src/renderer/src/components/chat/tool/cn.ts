/**
 * Minimal className joiner — deepseek has no `cn`/clsx utility, so the tool
 * layer ships its own. Filters falsy values and joins with spaces. Kept tiny
 * on purpose; nothing here should depend on tailwind-merge semantics.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
