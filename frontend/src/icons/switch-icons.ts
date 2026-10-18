/**
 * How a Material Design icon shows that its switch is on.
 *
 * Listed icons light only the part that glows (the glass of a bulb, the shade of a lamp); all other icons light
 * up completely. An outline icon gets the glowing part of its filled twin drawn behind the outline, so a
 * "lightbulb-outline" fills with light while the base keeps its colour.
 */
import { mdiPath } from './mdi-library'

// Indices of the subpaths ("M…" segments) of the filled icon that glow. Lit parts are drawn as one path, so a
// part and the hole cut into it (e.g. the filament of lightbulb-variant) must be listed together.
const GLOWING_SUBPATHS: Record<string, number[]> = {
  lightbulb: [0],
  'lightbulb-on': [0, 2, 3, 4, 5, 6],
  'lightbulb-variant': [1, 2],
  'ceiling-light': [1],
  lamp: [0],
  'floor-lamp': [0],
}

// Outline icons whose own subpaths also glow, e.g. the rays drawn around a bulb.
const GLOWING_OUTLINE_SUBPATHS: Record<string, number[]> = {
  'lightbulb-on-outline': [0, 1, 2, 3, 4],
}

export interface IconLayer {
  d: string
  fill: 'none' | 'currentColor'
  /** Coloured while the switch is on (CSS class "lit" under ".icon-on"). */
  lit: boolean
}

function subpaths(path: string) {
  return path.split(/(?=M)/)
}

export async function switchIconLayers(name: string, path: string): Promise<IconLayer[]> {
  const filledName = name.endsWith('-outline') ? name.slice(0, -'-outline'.length) : null
  const glowing = GLOWING_SUBPATHS[filledName ?? name]
  const whole: IconLayer[] = [{ d: path, fill: 'currentColor', lit: true }]
  if (!glowing) return whole

  if (filledName) {
    const filled = await mdiPath(filledName)
    if (!filled) return whole
    const parts = subpaths(filled)
    const outline = subpaths(path)
    const outlineGlowing = GLOWING_OUTLINE_SUBPATHS[name] ?? []
    return [
      { d: glowing.map((index) => parts[index]).join(''), fill: 'none', lit: true },
      { d: outline.filter((_, index) => !outlineGlowing.includes(index)).join(''), fill: 'currentColor', lit: false },
      { d: outlineGlowing.map((index) => outline[index]).join(''), fill: 'currentColor', lit: true },
    ]
  }

  const parts = subpaths(path)
  return [
    { d: parts.filter((_, index) => !glowing.includes(index)).join(''), fill: 'currentColor', lit: false },
    { d: glowing.map((index) => parts[index]).join(''), fill: 'currentColor', lit: true },
  ]
}
