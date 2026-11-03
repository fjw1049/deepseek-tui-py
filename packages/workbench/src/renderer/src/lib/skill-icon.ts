import {
  BookOpen, Braces, ChartNoAxesCombined, Compass, Feather, FileText,
  FlaskConical, Gem, Layers, Lightbulb, Orbit, Palette, PenTool,
  Puzzle, ScanSearch, Shapes, ShieldCheck, Sprout, Telescope, WandSparkles,
  type LucideIcon
} from 'lucide-react'

// A stable name-based choice keeps the same skill recognizable across views.
const icons = [
  BookOpen, Braces, ChartNoAxesCombined, Compass, Feather, FileText,
  FlaskConical, Gem, Layers, Lightbulb, Orbit, Palette, PenTool,
  Puzzle, ScanSearch, Shapes, ShieldCheck, Sprout, Telescope, WandSparkles
]

export function skillIcon(name: string): LucideIcon {
  let hash = 2166136261
  for (const char of name.trim().toLowerCase()) {
    hash = Math.imul(hash ^ char.codePointAt(0)!, 16777619)
  }
  return icons[(hash >>> 0) % icons.length]
}
